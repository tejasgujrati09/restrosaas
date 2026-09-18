"""Tab, order and service-request rules that need the database. The rules
themselves (undo window, cart validation, snapshots, totals) live in
`app.core`; this module loads rows, calls them and writes the results plus
the `TabEvent` for every state change (CLAUDE.md §3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ordering import (
    CartError,
    CartLine,
    LineSnapshot,
    OutletOrderRules,
    build_line_snapshot,
)
from app.core.pricing import PricedItem, effective_price
from app.core.state import (
    OrderState,
    TabState,
    can_customer_cancel_order_line,
    order_auto_accept_due,
    transition_order,
    transition_tab,
)
from app.deps import GuestContext
from app.domains.menu.orderable import LoadedItem, load_items, load_price_rules
from app.domains.tab.models import Order, OrderLine, ServiceRequest, Tab, TabEvent
from app.domains.tenant.models import Outlet
from app.errors import ApiError

LIVE_TAB_STATES = (TabState.OPEN.value, TabState.BILL_REQUESTED.value)
# Must be a literal, not bound parameters: Postgres only infers the partial unique
# index for ON CONFLICT when the predicate text matches, and after a few executions
# asyncpg switches to a generic plan where bound values never match.
LIVE_TAB_INDEX_PREDICATE = text("status IN ('open', 'bill_requested')")
_UNPROCESSABLE_CART_CODES = {"invalid_modifiers", "invalid_quantity", "unknown_item"}


def record_event(
    session: AsyncSession,
    *,
    restaurant_id: UUID,
    tab_id: UUID,
    at: datetime,
    actor_type: str,
    event: str,
    actor_user_id: UUID | None = None,
    actor_session_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    reason: str | None = None,
) -> TabEvent:
    row = TabEvent(
        restaurant_id=restaurant_id,
        tab_id=tab_id,
        at=at,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_session_id=actor_session_id,
        event=event,
        payload=payload or {},
        reason=reason,
    )
    session.add(row)
    return row


def guest_event(
    ctx: GuestContext, at: datetime, event: str, payload: dict[str, Any] | None = None
) -> TabEvent:
    return record_event(
        ctx.session,
        restaurant_id=ctx.restaurant_id,
        tab_id=ctx.tab_id,
        at=at,
        actor_type="customer",
        actor_session_id=ctx.tab_session_id,
        event=event,
        payload=payload,
    )


async def lock_live_tab(session: AsyncSession, tab_id: UUID) -> Tab:
    tab = await session.scalar(select(Tab).where(Tab.id == tab_id).with_for_update())
    if tab is None or tab.status not in LIVE_TAB_STATES:
        raise ApiError(
            401, "session_ended", "This table's session has ended. Scan the QR code again."
        )
    return tab


async def accept_due_orders(ctx: GuestContext, now: datetime) -> None:
    """Auto-accept rounds whose undo window has closed. The conditional UPDATE
    means concurrent readers accept each round, and log it, exactly once."""
    session = ctx.session
    placed = (
        await session.scalars(
            select(Order).where(Order.tab_id == ctx.tab_id, Order.status == OrderState.PLACED.value)
        )
    ).all()
    for order in placed:
        if not order_auto_accept_due(OrderState.PLACED, (now - order.placed_at).total_seconds()):
            continue
        accepted = await session.execute(
            update(Order)
            .where(Order.id == order.id, Order.status == OrderState.PLACED.value)
            .values(
                status=transition_order(OrderState.PLACED, OrderState.ACCEPTED).value,
                accepted_at=now,
            )
            .returning(Order.id)
        )
        if accepted.scalar_one_or_none() is None:
            continue
        await session.execute(
            update(OrderLine)
            .where(OrderLine.order_id == order.id, OrderLine.status == OrderState.PLACED.value)
            .values(status=OrderState.ACCEPTED.value)
        )
        record_event(
            session,
            restaurant_id=ctx.restaurant_id,
            tab_id=ctx.tab_id,
            at=now,
            actor_type="system",
            event="order_accepted",
            payload={"order_id": str(order.id), "seq_no": order.seq_no, "auto": True},
        )


async def build_snapshots(
    ctx: GuestContext, cart: list[CartLine], now: datetime
) -> tuple[Outlet, dict[UUID, LoadedItem], list[LineSnapshot]]:
    """Validates a cart against the live menu and prices it as of `now`. Shared
    by placing an order and by the cart preview, so what a guest is quoted is
    exactly what gets snapshotted."""
    session = ctx.session
    outlet = await session.get(Outlet, ctx.outlet_id)
    assert outlet is not None
    tz = ZoneInfo(outlet.timezone)
    local_now = now.astimezone(tz).time()
    rules = OutletOrderRules(
        liquor_licensed=outlet.liquor_licensed,
        liquor_approval_required=outlet.liquor_approval_required,
        prices_include_tax=outlet.prices_include_tax,
    )
    loaded = await load_items(
        session, ctx.outlet_id, outlet.liquor_vat_rate_bp, {c.menu_item_id for c in cart}
    )
    price_rules, rule_names = await load_price_rules(session, ctx.outlet_id)

    snapshots: list[LineSnapshot] = []
    try:
        for cart_line in cart:
            found = loaded.get(cart_line.menu_item_id)
            if found is None:
                raise CartError(
                    "unknown_item",
                    "One of the items is not on this menu.",
                    {"item_id": str(cart_line.menu_item_id)},
                )
            price = effective_price(
                PricedItem(found.row.id, found.row.category_id, found.row.base_price_paise),
                price_rules,
                now,
                tz,
            )
            name = rule_names.get(price.price_rule_id) if price.price_rule_id else None
            snapshots.append(
                build_line_snapshot(found.orderable, cart_line, rules, price, name, local_now)
            )
    except CartError as exc:
        status = 422 if exc.code in _UNPROCESSABLE_CART_CODES else 409
        raise ApiError(status, exc.code, exc.message, exc.details) from exc
    return outlet, loaded, snapshots


@dataclass(frozen=True)
class PlacedOrder:
    order: Order
    lines: list[OrderLine]


async def place_customer_order(
    ctx: GuestContext, cart: list[CartLine], notes: dict[int, str | None], now: datetime
) -> PlacedOrder:
    session = ctx.session
    tab = await lock_live_tab(session, ctx.tab_id)
    if tab.confirmed_at is None:
        raise ApiError(
            409, "awaiting_waiter", "Your waiter needs to confirm your table before you can order."
        )
    await accept_due_orders(ctx, now)

    _, loaded, snapshots = await build_snapshots(ctx, cart, now)

    seq_no = (
        await session.scalar(select(func.max(Order.seq_no)).where(Order.tab_id == ctx.tab_id))
    ) or 0
    order = Order(
        restaurant_id=ctx.restaurant_id,
        outlet_id=ctx.outlet_id,
        tab_id=ctx.tab_id,
        seq_no=seq_no + 1,
        status=OrderState.PLACED.value,
        fulfillment_type="dine_in",
        placed_at=now,
        placed_by_session_id=ctx.tab_session_id,
        source="customer",
    )
    session.add(order)
    await session.flush()

    lines: list[OrderLine] = []
    for index, snap in enumerate(snapshots):
        line = OrderLine(
            restaurant_id=ctx.restaurant_id,
            order_id=order.id,
            tab_id=ctx.tab_id,
            menu_item_id=snap.menu_item_id,
            item_name_snapshot=snap.item_name,
            qty=snap.qty,
            unit_price_snapshot=snap.unit_price_paise,
            price_rule_id=snap.price_rule_id,
            price_rule_name_snapshot=snap.price_rule_name,
            tax_class_snapshot=snap.tax_class,
            modifiers_snapshot=list(snap.modifiers),
            line_total=snap.line_total_paise,
            status=OrderState.PLACED.value,
            placed_by="customer",
            needs_customer_ack=False,
            notes=notes.get(index),
        )
        session.add(line)
        lines.append(line)
    await session.flush()

    for snap, line in zip(snapshots, lines, strict=True):
        guest_event(
            ctx,
            now,
            "line_added",
            {
                "order_id": str(order.id),
                "line_id": str(line.id),
                "item": snap.item_name,
                "qty": snap.qty,
                "unit_price_paise": snap.unit_price_paise,
                "line_total_paise": snap.line_total_paise,
                "modifiers": [m["name"] for m in snap.modifiers],
            },
        )
        if snap.price_rule_id is not None:
            guest_event(
                ctx,
                now,
                "price_rule_applied",
                {
                    "line_id": str(line.id),
                    "price_rule_id": str(snap.price_rule_id),
                    "price_rule_name": snap.price_rule_name,
                    "base_price_paise": loaded[snap.menu_item_id].row.base_price_paise,
                    "unit_price_paise": snap.unit_price_paise,
                },
            )
    guest_event(
        ctx,
        now,
        "order_placed",
        {
            "order_id": str(order.id),
            "seq_no": order.seq_no,
            "line_count": len(lines),
            "total_paise": sum(line.line_total for line in lines),
        },
    )

    if TabState(tab.status) == TabState.BILL_REQUESTED:
        tab.status = transition_tab(TabState.BILL_REQUESTED, TabState.OPEN).value
        guest_event(ctx, now, "bill_request_cleared", {"order_id": str(order.id)})
    return PlacedOrder(order, lines)


async def undo_order(ctx: GuestContext, order_id: UUID, now: datetime) -> Order:
    session = ctx.session
    await accept_due_orders(ctx, now)
    order = await session.scalar(
        select(Order).where(Order.id == order_id, Order.tab_id == ctx.tab_id)
    )
    if order is None:
        raise ApiError(404, "not_found", "Order not found.")
    if order.placed_by_session_id != ctx.tab_session_id:
        raise ApiError(403, "not_your_order", "Only the phone that placed this order can undo it.")
    if not can_customer_cancel_order_line(
        OrderState(order.status), (now - order.placed_at).total_seconds()
    ):
        raise ApiError(
            409,
            "undo_window_closed",
            "It's too late to undo this order. Ask your waiter.",
            {"status": order.status},
        )
    target = transition_order(OrderState.PLACED, OrderState.CANCELLED)
    cancelled = await session.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == OrderState.PLACED.value)
        .values(status=target.value, cancelled_at=now)
        .returning(Order.id)
    )
    if cancelled.scalar_one_or_none() is None:
        raise ApiError(
            409, "undo_window_closed", "It's too late to undo this order. Ask your waiter."
        )
    await session.execute(
        update(OrderLine).where(OrderLine.order_id == order.id).values(status="cancelled")
    )
    await session.refresh(order)
    guest_event(
        ctx,
        now,
        "order_cancelled",
        {"order_id": str(order.id), "seq_no": order.seq_no, "by": "customer"},
    )
    return order


async def set_service_charge_removed(ctx: GuestContext, removed: bool, now: datetime) -> Tab:
    tab = await lock_live_tab(ctx.session, ctx.tab_id)
    if tab.service_charge_removed != removed:
        tab.service_charge_removed = removed
        guest_event(ctx, now, "service_charge_changed", {"removed": removed})
    return tab


async def create_service_request(
    ctx: GuestContext, request_type: str, now: datetime
) -> ServiceRequest:
    """One open request per (tab, type): tapping "Call waiter" twice does not
    ring twice. A bill request also moves the tab to `bill_requested`."""
    session = ctx.session
    tab = await lock_live_tab(session, ctx.tab_id)
    if request_type == "bill":
        billable = await session.scalar(
            select(func.count())
            .select_from(OrderLine)
            .where(OrderLine.tab_id == ctx.tab_id, OrderLine.status.not_in(("cancelled", "voided")))
        )
        if not billable:
            raise ApiError(409, "nothing_to_bill", "Order something first, then ask for the bill.")

    created = await session.scalar(
        insert(ServiceRequest)
        .values(
            id=uuid4(),
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            tab_id=ctx.tab_id,
            type=request_type,
            created_at=now,
            created_by_session_id=ctx.tab_session_id,
        )
        .on_conflict_do_nothing(
            index_elements=[ServiceRequest.tab_id, ServiceRequest.type],
            index_where=ServiceRequest.resolved_at.is_(None),
        )
        .returning(ServiceRequest.id)
    )
    if created is None:
        request = await session.scalar(
            select(ServiceRequest).where(
                ServiceRequest.tab_id == ctx.tab_id,
                ServiceRequest.type == request_type,
                ServiceRequest.resolved_at.is_(None),
            )
        )
        assert request is not None
        # Items were added after an earlier, still-unresolved bill request, which
        # moved the tab back to open: asking again must flag the tab again.
        if request_type == "bill" and TabState(tab.status) == TabState.OPEN:
            tab.status = transition_tab(TabState.OPEN, TabState.BILL_REQUESTED).value
            guest_event(ctx, now, "bill_requested", {"request_id": str(request.id)})
        return request

    request = await session.get(ServiceRequest, created)
    assert request is not None
    if request_type == "bill":
        if TabState(tab.status) == TabState.OPEN:
            tab.status = transition_tab(TabState.OPEN, TabState.BILL_REQUESTED).value
        guest_event(ctx, now, "bill_requested", {"request_id": str(request.id)})
    else:
        guest_event(
            ctx, now, "service_requested", {"request_id": str(request.id), "type": request_type}
        )
    return request
