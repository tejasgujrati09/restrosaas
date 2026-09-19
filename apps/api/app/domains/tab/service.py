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
    decide_staff_line_ack,
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
from app.deps import GuestContext, OutletContext
from app.domains.menu.orderable import LoadedItem, load_items, load_price_rules
from app.domains.tab.events import Actor, emit, record_event  # noqa: F401
from app.domains.tab.models import Order, OrderLine, ServiceRequest, Tab, TabEvent, TabSession
from app.domains.tab.tickets import cancel_order_tickets, create_tickets
from app.domains.tenant.models import Outlet
from app.errors import ApiError
from app.realtime.scheduler import schedule_auto_accept

LIVE_TAB_STATES = (TabState.OPEN.value, TabState.BILL_REQUESTED.value)
# Must be a literal, not bound parameters: Postgres only infers the partial unique
# index for ON CONFLICT when the predicate text matches, and after a few executions
# asyncpg switches to a generic plan where bound values never match.
LIVE_TAB_INDEX_PREDICATE = text("status IN ('open', 'bill_requested')")
_UNPROCESSABLE_CART_CODES = {"invalid_modifiers", "invalid_quantity", "unknown_item"}


def guest_actor(ctx: GuestContext) -> Actor:
    return Actor("customer", session_id=ctx.tab_session_id)


def guest_event(
    ctx: GuestContext, at: datetime, event: str, payload: dict[str, Any] | None = None
) -> TabEvent:
    return emit(
        ctx.session,
        restaurant_id=ctx.restaurant_id,
        tab_id=ctx.tab_id,
        table_id=ctx.table_id,
        at=at,
        actor=guest_actor(ctx),
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


async def accept_due_orders(
    session: AsyncSession, restaurant_id: UUID, tab_id: UUID, now: datetime
) -> None:
    """Auto-accept rounds whose undo window has closed. The conditional UPDATE
    means concurrent readers accept each round, and log it, exactly once."""
    placed = (
        await session.scalars(
            select(Order).where(
                Order.tab_id == tab_id,
                Order.status == OrderState.PLACED.value,
                # A phone order is accepted by a person, never by the clock.
                Order.source != "voice",
            )
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
            restaurant_id=restaurant_id,
            tab_id=tab_id,
            at=now,
            actor_type="system",
            event="order_accepted",
            payload={"order_id": str(order.id), "seq_no": order.seq_no, "auto": True},
        )


async def build_snapshots(
    session: AsyncSession,
    outlet_id: UUID,
    cart: list[CartLine],
    now: datetime,
    *,
    by_staff: bool = False,
    approval_granted: bool = False,
) -> tuple[Outlet, dict[UUID, LoadedItem], list[LineSnapshot]]:
    """Validates a cart against the live menu and prices it as of `now`. Shared
    by placing an order and by the cart preview, so what a guest is quoted is
    exactly what gets snapshotted. `approval_granted` (a manager or owner adding
    the line) satisfies the outlet's liquor-approval rule."""
    outlet = await session.get(Outlet, outlet_id)
    assert outlet is not None
    tz = ZoneInfo(outlet.timezone)
    local_now = now.astimezone(tz).time()
    rules = OutletOrderRules(
        liquor_licensed=outlet.liquor_licensed,
        liquor_approval_required=outlet.liquor_approval_required and not approval_granted,
        prices_include_tax=outlet.prices_include_tax,
    )
    loaded = await load_items(
        session, outlet_id, outlet.liquor_vat_rate_bp, {c.menu_item_id for c in cart}
    )
    price_rules, rule_names = await load_price_rules(session, outlet_id)

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
        if by_staff and exc.code == "needs_waiter":
            raise ApiError(
                409,
                "needs_manager",
                "A manager must approve this item before it can be added.",
                exc.details,
            ) from exc
        status = 422 if exc.code in _UNPROCESSABLE_CART_CODES else 409
        raise ApiError(status, exc.code, exc.message, exc.details) from exc
    return outlet, loaded, snapshots


@dataclass(frozen=True)
class PlacedOrder:
    order: Order
    lines: list[OrderLine]


@dataclass(frozen=True)
class OrderOrigin:
    """An order that did not come from a table: a phone call. Its round waits for a
    manager or owner to accept it (docs/DECISIONS.md "Voice ordering agent")."""

    source: str
    fulfillment_type: str
    customer_id: UUID | None = None
    address_id: UUID | None = None
    delivery_address_snapshot: str | None = None
    external_call_id: str | None = None


async def create_round(
    session: AsyncSession,
    *,
    restaurant_id: UUID,
    outlet_id: UUID,
    tab: Tab,
    snapshots: list[LineSnapshot],
    notes: dict[int, str | None],
    loaded: dict[UUID, LoadedItem],
    actor: Actor,
    now: datetime,
    outlet: Outlet,
    origin: OrderOrigin | None = None,
) -> PlacedOrder:
    """A round of lines, its tickets and its events. A guest's round waits out the
    undo window as `placed`; a waiter's is accepted at once and lines above the ack
    threshold need the guest's tap (or, with nobody on the tab to ask, are waived)."""
    by_staff = actor.actor_type == "staff"
    seq_no = (
        await session.scalar(select(func.max(Order.seq_no)).where(Order.tab_id == tab.id))
    ) or 0
    status = OrderState.ACCEPTED if by_staff else OrderState.PLACED
    order = Order(
        restaurant_id=restaurant_id,
        outlet_id=outlet_id,
        tab_id=tab.id,
        seq_no=seq_no + 1,
        status=status.value,
        fulfillment_type=origin.fulfillment_type if origin else "dine_in",
        placed_at=now,
        placed_by_user_id=actor.user_id if by_staff else None,
        placed_by_session_id=None if by_staff else actor.session_id,
        source=origin.source if origin else ("waiter" if by_staff else "customer"),
        accepted_at=now if by_staff else None,
        customer_id=origin.customer_id if origin else None,
        address_id=origin.address_id if origin else None,
        delivery_address_snapshot=origin.delivery_address_snapshot if origin else None,
        external_call_id=origin.external_call_id if origin else None,
    )
    session.add(order)
    await session.flush()

    has_live_session = False
    if by_staff:
        live = await session.scalar(
            select(func.count())
            .select_from(TabSession)
            .where(
                TabSession.tab_id == tab.id,
                TabSession.revoked.is_(False),
                TabSession.expires_at > now,
            )
        )
        has_live_session = bool(live)

    lines: list[OrderLine] = []
    acks = []
    for index, snap in enumerate(snapshots):
        ack = (
            decide_staff_line_ack(
                line_total_paise=snap.line_total_paise,
                threshold_paise=outlet.ack_threshold_paise,
                has_live_session=has_live_session,
            )
            if by_staff
            else None
        )
        acks.append(ack)
        line = OrderLine(
            restaurant_id=restaurant_id,
            order_id=order.id,
            tab_id=tab.id,
            menu_item_id=snap.menu_item_id,
            item_name_snapshot=snap.item_name,
            qty=snap.qty,
            unit_price_snapshot=snap.unit_price_paise,
            price_rule_id=snap.price_rule_id,
            price_rule_name_snapshot=snap.price_rule_name,
            tax_class_snapshot=snap.tax_class,
            modifiers_snapshot=list(snap.modifiers),
            line_total=snap.line_total_paise,
            status=status.value,
            placed_by="staff" if by_staff else "customer",
            staff_user_id=actor.user_id if by_staff else None,
            needs_customer_ack=bool(ack and ack.needs_customer_ack),
            notes=notes.get(index),
            position=index,
        )
        session.add(line)
        lines.append(line)
    await session.flush()
    await create_tickets(session, restaurant_id, outlet_id, order, lines, loaded, now)

    def log(event: str, payload: dict[str, Any]) -> None:
        emit(
            session,
            restaurant_id=restaurant_id,
            tab_id=tab.id,
            table_id=tab.table_id,
            at=now,
            actor=actor,
            event=event,
            payload=payload,
        )

    for snap, line, ack in zip(snapshots, lines, acks, strict=True):
        payload: dict[str, Any] = {
            "order_id": str(order.id),
            "line_id": str(line.id),
            "item": snap.item_name,
            "qty": snap.qty,
            "unit_price_paise": snap.unit_price_paise,
            "line_total_paise": snap.line_total_paise,
            "modifiers": [m["name"] for m in snap.modifiers],
        }
        if by_staff and ack is not None:
            payload["needs_customer_ack"] = ack.needs_customer_ack
            if ack.ack_waived:
                payload["ack_waived"] = True
        log("line_added", payload)
        if snap.price_rule_id is not None:
            log(
                "price_rule_applied",
                {
                    "line_id": str(line.id),
                    "price_rule_id": str(snap.price_rule_id),
                    "price_rule_name": snap.price_rule_name,
                    "base_price_paise": loaded[snap.menu_item_id].row.base_price_paise,
                    "unit_price_paise": snap.unit_price_paise,
                },
            )
    placed_payload: dict[str, Any] = {
        "order_id": str(order.id),
        "seq_no": order.seq_no,
        "line_count": len(lines),
        "total_paise": sum(line.line_total for line in lines),
        "source": order.source,
    }
    if origin is not None:
        placed_payload["channel"] = origin.source
        placed_payload["call_id"] = origin.external_call_id
    log("order_placed", placed_payload)
    if TabState(tab.status) == TabState.BILL_REQUESTED:
        tab.status = transition_tab(TabState.BILL_REQUESTED, TabState.OPEN).value
        log("bill_request_cleared", {"order_id": str(order.id)})
    return PlacedOrder(order, lines)


async def place_customer_order(
    ctx: GuestContext, cart: list[CartLine], notes: dict[int, str | None], now: datetime
) -> PlacedOrder:
    session = ctx.session
    tab = await lock_live_tab(session, ctx.tab_id)
    if tab.confirmed_at is None:
        raise ApiError(
            409, "awaiting_waiter", "Your waiter needs to confirm your table before you can order."
        )
    await accept_due_orders(session, ctx.restaurant_id, ctx.tab_id, now)
    outlet, loaded, snapshots = await build_snapshots(session, ctx.outlet_id, cart, now)
    placed = await create_round(
        session,
        restaurant_id=ctx.restaurant_id,
        outlet_id=ctx.outlet_id,
        tab=tab,
        snapshots=snapshots,
        notes=notes,
        loaded=loaded,
        actor=guest_actor(ctx),
        now=now,
        outlet=outlet,
    )
    schedule_auto_accept(session, ctx.restaurant_id, ctx.outlet_id, ctx.tab_id, now)
    return placed


async def place_staff_order(
    ctx: OutletContext,
    tab: Tab,
    cart: list[CartLine],
    notes: dict[int, str | None],
    now: datetime,
    *,
    approval_granted: bool,
) -> PlacedOrder:
    """A waiter adds a round for the guest. `tab` is already locked and access-checked."""
    outlet, loaded, snapshots = await build_snapshots(
        ctx.session, ctx.outlet_id, cart, now, by_staff=True, approval_granted=approval_granted
    )
    return await create_round(
        ctx.session,
        restaurant_id=ctx.restaurant_id,
        outlet_id=ctx.outlet_id,
        tab=tab,
        snapshots=snapshots,
        notes=notes,
        loaded=loaded,
        actor=Actor("staff", user_id=ctx.actor.user_id),
        now=now,
        outlet=outlet,
    )


async def undo_order(ctx: GuestContext, order_id: UUID, now: datetime) -> Order:
    session = ctx.session
    await accept_due_orders(session, ctx.restaurant_id, ctx.tab_id, now)
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
    await cancel_order_tickets(session, order.id)
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


async def _pending_voice_order(session: AsyncSession, outlet_id: UUID, order_id: UUID) -> Order:
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id, Order.outlet_id == outlet_id, Order.source == "voice")
        .with_for_update()
    )
    if order is None:
        raise ApiError(404, "not_found", "Order not found.")
    if order.status != OrderState.PLACED.value:
        raise ApiError(
            409,
            "order_not_pending",
            "This order is no longer waiting for acceptance.",
            {"status": order.status},
        )
    return order


async def accept_voice_order(
    ctx: OutletContext, order_id: UUID, now: datetime
) -> tuple[Order, list[OrderLine]]:
    """A manager or owner accepts a phone order: it becomes `accepted`, so the kitchen can
    start its ticket. Conditional on still being `placed`, so a double tap accepts once."""
    session = ctx.session
    order = await _pending_voice_order(session, ctx.outlet_id, order_id)
    target = transition_order(OrderState.PLACED, OrderState.ACCEPTED)
    order.status = target.value
    order.accepted_at = now
    await session.execute(
        update(OrderLine)
        .where(OrderLine.order_id == order.id, OrderLine.status == OrderState.PLACED.value)
        .values(status=target.value)
    )
    emit(
        session,
        restaurant_id=ctx.restaurant_id,
        tab_id=order.tab_id,
        table_id=None,
        at=now,
        actor=Actor("staff", user_id=ctx.actor.user_id),
        event="order_accepted",
        payload={"order_id": str(order.id), "seq_no": order.seq_no, "auto": False},
    )
    lines = list(
        await session.scalars(
            select(OrderLine)
            .where(OrderLine.order_id == order.id)
            .order_by(OrderLine.position, OrderLine.id)
        )
    )
    return order, lines


async def reject_voice_order(
    ctx: OutletContext, order_id: UUID, reason: str, now: datetime
) -> tuple[Order, list[OrderLine]]:
    """A manager or owner declines a phone order. The round is cancelled with a reason and
    its kitchen ticket is withdrawn. The tab stays open for the restaurant to close."""
    session = ctx.session
    order = await _pending_voice_order(session, ctx.outlet_id, order_id)
    order.status = transition_order(OrderState.PLACED, OrderState.CANCELLED).value
    order.cancelled_at = now
    await session.execute(
        update(OrderLine).where(OrderLine.order_id == order.id).values(status="cancelled")
    )
    await cancel_order_tickets(session, order.id)
    emit(
        session,
        restaurant_id=ctx.restaurant_id,
        tab_id=order.tab_id,
        table_id=None,
        at=now,
        actor=Actor("staff", user_id=ctx.actor.user_id),
        event="order_cancelled",
        payload={"order_id": str(order.id), "seq_no": order.seq_no, "by": "staff"},
        reason=reason,
    )
    lines = list(
        await session.scalars(
            select(OrderLine)
            .where(OrderLine.order_id == order.id)
            .order_by(OrderLine.position, OrderLine.id)
        )
    )
    return order, lines
