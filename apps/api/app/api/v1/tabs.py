"""The guest's tab: placing rounds, undo, the live view, service charge and
service requests. Guests authenticate with a TabSession token and may act only
on their own tab (`assert_can_write_own_tab`). Staff confirm a tab here too,
through the normal role matrix."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.api.v1.common import (
    ERRORS,
    Ctx,
    GuestCtx,
    IdempotencyKeyHeader,
    guest_idempotent_write,
    idempotent_write,
    not_found,
)
from app.core.ordering import MAX_QTY, CartLine
from app.core.permissions import Capability, assert_can, assert_can_write_own_tab
from app.core.state import CUSTOMER_UNDO_WINDOW_SECONDS, OrderState
from app.core.tab_totals import TabTotals, TotalsLine, compute_tab_totals
from app.domains.staff.models import AppUser
from app.domains.tab import service
from app.domains.tab.access import require_table_access
from app.domains.tab.events import record_event
from app.domains.tab.models import Order, OrderLine, ServiceRequest, Tab
from app.domains.tenant.models import DiningTable, Outlet
from app.errors import ApiError

router = APIRouter(prefix="/v1/outlets/{outlet_id}/tabs/{tab_id}", tags=["tabs"])

_INACTIVE_LINE = ("cancelled", "voided")


class CartLineIn(BaseModel):
    menu_item_id: UUID
    qty: int = Field(ge=1, le=MAX_QTY)
    modifier_ids: list[UUID] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=200)


class PlaceOrderIn(BaseModel):
    lines: list[CartLineIn] = Field(min_length=1, max_length=30)


class ModifierOut(BaseModel):
    name: str
    price_delta_paise: int


class RuleRefOut(BaseModel):
    id: UUID
    name: str | None


class LineOut(BaseModel):
    id: UUID
    name: str
    qty: int
    unit_price_paise: int
    modifiers: list[ModifierOut]
    line_total_paise: int
    status: str
    placed_by: Literal["customer", "staff"]
    by_you: bool
    staff_name: str | None
    price_rule: RuleRefOut | None
    needs_customer_ack: bool
    acked_at: datetime | None
    disputed_at: datetime | None
    # not_needed | awaiting | acked | disputed (staff-added lines above the threshold only)
    ack_state: str
    note: str | None
    voided_at: datetime | None
    void_reason: str | None


class RoundOut(BaseModel):
    id: UUID
    seq_no: int
    status: str
    placed_at: datetime
    # While set, the guest may still undo the whole round.
    undo_until: datetime | None
    lines: list[LineOut]


class TotalsOut(BaseModel):
    items_paise: int
    taxable_value_paise: int
    cgst_paise: int
    sgst_paise: int
    liquor_vat_paise: int
    service_charge_paise: int
    service_charge_bp: int
    service_charge_removed: bool
    estimated_total_paise: int
    prices_include_tax: bool
    # The bill is computed once at close; until then this is an estimate.
    is_estimate: bool = True


class TabOut(BaseModel):
    id: UUID
    status: str
    table_label: str | None
    awaiting_waiter: bool
    opened_at: datetime
    rounds: list[RoundOut]
    totals: TotalsOut
    open_requests: list[str]


class QuoteLineOut(BaseModel):
    menu_item_id: UUID
    name: str
    qty: int
    unit_price_paise: int
    modifiers: list[ModifierOut]
    line_total_paise: int
    price_rule: RuleRefOut | None


class QuoteOut(BaseModel):
    lines: list[QuoteLineOut]
    # Tax split and service charge for this cart alone, as they will be on the tab.
    totals: TotalsOut
    # False while the tab waits for a waiter's confirmation.
    can_order: bool


class ServiceChargeIn(BaseModel):
    removed: bool


class ServiceRequestIn(BaseModel):
    type: Literal["waiter", "water", "bill"]


class ServiceRequestOut(BaseModel):
    id: UUID
    type: str
    created_at: datetime
    tab_status: str


class ConfirmOut(BaseModel):
    tab_id: UUID
    confirmed_at: datetime


def _ack_state(line: OrderLine) -> str:
    if not line.needs_customer_ack:
        return "not_needed"
    if line.disputed_at is not None:
        return "disputed"
    return "acked" if line.acked_at is not None else "awaiting"


def _line_out(
    line: OrderLine, order: Order, ctx_session_id: UUID | None, staff_names: dict[UUID, str | None]
) -> LineOut:
    return LineOut(
        id=line.id,
        name=line.item_name_snapshot,
        qty=line.qty,
        unit_price_paise=line.unit_price_snapshot,
        modifiers=[
            ModifierOut(name=m["name"], price_delta_paise=m["price_delta_paise"])
            for m in line.modifiers_snapshot
        ],
        line_total_paise=line.line_total,
        status=line.status,
        placed_by="staff" if line.placed_by == "staff" else "customer",
        by_you=ctx_session_id is not None and order.placed_by_session_id == ctx_session_id,
        staff_name=staff_names.get(line.staff_user_id) if line.staff_user_id else None,
        price_rule=(
            RuleRefOut(id=line.price_rule_id, name=line.price_rule_name_snapshot)
            if line.price_rule_id
            else None
        ),
        needs_customer_ack=line.needs_customer_ack,
        acked_at=line.acked_at,
        disputed_at=line.disputed_at,
        ack_state=_ack_state(line),
        note=line.notes,
        voided_at=line.voided_at,
        void_reason=line.void_reason,
    )


def _round_out(
    order: Order,
    lines: list[OrderLine],
    session_id: UUID | None,
    staff_names: dict[UUID, str | None],
) -> RoundOut:
    undo_until = (
        order.placed_at + timedelta(seconds=CUSTOMER_UNDO_WINDOW_SECONDS)
        if order.status == OrderState.PLACED.value
        else None
    )
    return RoundOut(
        id=order.id,
        seq_no=order.seq_no,
        status=order.status,
        placed_at=order.placed_at,
        undo_until=undo_until,
        lines=[_line_out(line, order, session_id, staff_names) for line in lines],
    )


async def _staff_names(session: Any, lines: list[OrderLine]) -> dict[UUID, str | None]:
    ids = {line.staff_user_id for line in lines if line.staff_user_id}
    if not ids:
        return {}
    rows = await session.execute(select(AppUser.id, AppUser.name).where(AppUser.id.in_(ids)))
    return {user_id: name for user_id, name in rows}


@router.post("/orders", status_code=201, responses=ERRORS)
async def place_order(
    tab_id: UUID, ctx: GuestCtx, key: IdempotencyKeyHeader, body: PlaceOrderIn
) -> RoundOut:
    """Places a round. Every name, price, tax class and modifier is copied onto the
    lines; safe to resend with the same `Idempotency-Key`."""
    assert_can_write_own_tab(ctx.actor, tab_id)

    async def produce() -> RoundOut:
        now = clock.utcnow()
        cart = [CartLine(c.menu_item_id, c.qty, tuple(c.modifier_ids)) for c in body.lines]
        notes = {i: c.note for i, c in enumerate(body.lines)}
        placed = await service.place_customer_order(ctx, cart, notes, now)
        return _round_out(placed.order, placed.lines, ctx.tab_session_id, {})

    return await guest_idempotent_write(
        ctx, key, f"POST tabs/{tab_id}/orders", body, RoundOut, produce
    )


@router.post("/cart/quote", responses=ERRORS)
async def quote_cart(tab_id: UUID, ctx: GuestCtx, body: PlaceOrderIn) -> QuoteOut:
    """Prices a cart without placing it, using the same validation and snapshot code
    as placing an order, so the cart screen never does money maths of its own.
    Read-only: nothing is written."""
    assert_can_write_own_tab(ctx.actor, tab_id)
    tab = await service.lock_live_tab(ctx.session, tab_id)
    cart = [CartLine(c.menu_item_id, c.qty, tuple(c.modifier_ids)) for c in body.lines]
    outlet, _, snapshots = await service.build_snapshots(
        ctx.session, ctx.outlet_id, cart, clock.utcnow()
    )
    totals = compute_tab_totals(
        [
            TotalsLine(
                unit_gross_paise=s.unit_gross_paise,
                qty=s.qty,
                rate_bp=s.tax_class["rate_bp"],
                is_liquor=s.tax_class["is_liquor"],
                prices_include_tax=s.tax_class["prices_include_tax"],
            )
            for s in snapshots
        ],
        service_charge_bp=outlet.service_charge_bp,
        service_charge_removed=tab.service_charge_removed,
    )
    return QuoteOut(
        lines=[
            QuoteLineOut(
                menu_item_id=s.menu_item_id,
                name=s.item_name,
                qty=s.qty,
                unit_price_paise=s.unit_price_paise,
                modifiers=[
                    ModifierOut(name=m["name"], price_delta_paise=m["price_delta_paise"])
                    for m in s.modifiers
                ],
                line_total_paise=s.line_total_paise,
                price_rule=(
                    RuleRefOut(id=s.price_rule_id, name=s.price_rule_name)
                    if s.price_rule_id
                    else None
                ),
            )
            for s in snapshots
        ],
        totals=_totals_out(totals, outlet, tab),
        can_order=tab.confirmed_at is not None,
    )


@router.post("/orders/{order_id}/undo", responses=ERRORS)
async def undo_order(
    tab_id: UUID, order_id: UUID, ctx: GuestCtx, key: IdempotencyKeyHeader
) -> RoundOut:
    """Cancels a round within 60 seconds, before it is accepted. After that only a
    manager can void, with a reason."""
    assert_can_write_own_tab(ctx.actor, tab_id)

    async def produce() -> RoundOut:
        order = await service.undo_order(ctx, order_id, clock.utcnow())
        lines = (
            await ctx.session.scalars(
                select(OrderLine)
                .where(OrderLine.order_id == order.id)
                .order_by(OrderLine.position, OrderLine.id)
            )
        ).all()
        return _round_out(order, list(lines), ctx.tab_session_id, {})

    return await guest_idempotent_write(
        ctx, key, f"POST tabs/{tab_id}/orders/{order_id}/undo", None, RoundOut, produce
    )


def _totals_out(totals: TabTotals, outlet: Outlet, tab: Tab) -> TotalsOut:
    return TotalsOut(
        items_paise=totals.items_paise,
        taxable_value_paise=totals.taxable_value_paise,
        cgst_paise=totals.cgst_paise,
        sgst_paise=totals.sgst_paise,
        liquor_vat_paise=totals.liquor_vat_paise,
        service_charge_paise=totals.service_charge_paise,
        service_charge_bp=outlet.service_charge_bp,
        service_charge_removed=tab.service_charge_removed,
        estimated_total_paise=totals.estimated_total_paise,
        prices_include_tax=outlet.prices_include_tax,
    )


async def build_tab_out(
    session: AsyncSession, outlet_id: UUID, tab: Tab, viewer_session_id: UUID | None
) -> TabOut:
    """The live tab as one viewer sees it: a guest's phone (`viewer_session_id`) or staff (None)."""
    outlet = await session.get(Outlet, outlet_id)
    assert outlet is not None
    table_label = None
    if tab.table_id is not None:
        table = await session.get(DiningTable, tab.table_id)
        table_label = table.label if table else None

    orders = (
        await session.scalars(select(Order).where(Order.tab_id == tab.id).order_by(Order.seq_no))
    ).all()
    lines = (
        await session.scalars(
            select(OrderLine)
            .where(OrderLine.tab_id == tab.id)
            .order_by(OrderLine.position, OrderLine.id)
        )
    ).all()
    lines_by_order: dict[UUID, list[OrderLine]] = {}
    for line in lines:
        lines_by_order.setdefault(line.order_id, []).append(line)
    names = await _staff_names(session, list(lines))

    active_orders = {o.id for o in orders if o.status != OrderState.CANCELLED.value}
    totals_lines = [
        TotalsLine(
            unit_gross_paise=line.line_total // line.qty,
            qty=line.qty,
            rate_bp=line.tax_class_snapshot["rate_bp"],
            is_liquor=line.tax_class_snapshot["is_liquor"],
            prices_include_tax=line.tax_class_snapshot["prices_include_tax"],
        )
        for line in lines
        if line.order_id in active_orders and line.status not in _INACTIVE_LINE
    ]
    totals = compute_tab_totals(
        totals_lines,
        service_charge_bp=outlet.service_charge_bp,
        service_charge_removed=tab.service_charge_removed,
    )
    open_requests = (
        await session.scalars(
            select(ServiceRequest.type).where(
                ServiceRequest.tab_id == tab.id, ServiceRequest.resolved_at.is_(None)
            )
        )
    ).all()
    return TabOut(
        id=tab.id,
        status=tab.status,
        table_label=table_label,
        awaiting_waiter=tab.confirmed_at is None,
        opened_at=tab.opened_at,
        rounds=[
            _round_out(o, lines_by_order.get(o.id, []), viewer_session_id, names) for o in orders
        ],
        totals=_totals_out(totals, outlet, tab),
        open_requests=sorted(open_requests),
    )


@router.get("", responses=ERRORS)
async def get_tab(tab_id: UUID, ctx: GuestCtx) -> TabOut:
    """The live tab: rounds, per-line source and status, the running total."""
    assert_can_write_own_tab(ctx.actor, tab_id)
    await service.accept_due_orders(ctx.session, ctx.restaurant_id, ctx.tab_id, clock.utcnow())
    tab = await ctx.session.get(Tab, tab_id)
    assert tab is not None
    return await build_tab_out(ctx.session, ctx.outlet_id, tab, ctx.tab_session_id)


@router.put("/service-charge", responses=ERRORS)
async def set_service_charge(
    tab_id: UUID, ctx: GuestCtx, key: IdempotencyKeyHeader, body: ServiceChargeIn
) -> TabOut:
    """Removing service charge is the guest's right: not a void, no reason needed."""
    assert_can_write_own_tab(ctx.actor, tab_id)

    async def produce() -> TabOut:
        tab = await service.set_service_charge_removed(ctx, body.removed, clock.utcnow())
        return await build_tab_out(ctx.session, ctx.outlet_id, tab, ctx.tab_session_id)

    return await guest_idempotent_write(
        ctx, key, f"PUT tabs/{tab_id}/service-charge", body, TabOut, produce
    )


@router.post("/service-requests", status_code=201, responses=ERRORS)
async def create_service_request(
    tab_id: UUID, ctx: GuestCtx, key: IdempotencyKeyHeader, body: ServiceRequestIn
) -> ServiceRequestOut:
    assert_can_write_own_tab(ctx.actor, tab_id)

    async def produce() -> ServiceRequestOut:
        request = await service.create_service_request(ctx, body.type, clock.utcnow())
        tab = await ctx.session.get(Tab, tab_id)
        assert tab is not None
        return ServiceRequestOut(
            id=request.id, type=request.type, created_at=request.created_at, tab_status=tab.status
        )

    return await guest_idempotent_write(
        ctx, key, f"POST tabs/{tab_id}/service-requests", body, ServiceRequestOut, produce
    )


class AckIn(BaseModel):
    answer: Literal["ours", "not_ours"]


@router.post("/lines/{line_id}/ack", responses=ERRORS)
async def answer_ack(
    tab_id: UUID, line_id: UUID, ctx: GuestCtx, key: IdempotencyKeyHeader, body: AckIn
) -> LineOut:
    """The guest's answer to a staff-added line: "Yes, ours" or "Not ours". Neither
    removes the line; "Not ours" raises an alert for a manager, who can void it."""
    assert_can_write_own_tab(ctx.actor, tab_id)

    async def produce() -> LineOut:
        now = clock.utcnow()
        line = await ctx.session.scalar(
            select(OrderLine).where(OrderLine.id == line_id, OrderLine.tab_id == tab_id)
        )
        if line is None:
            raise not_found("Line")
        order = await ctx.session.get(Order, line.order_id)
        assert order is not None
        if not line.needs_customer_ack:
            raise ApiError(409, "no_ack_needed", "This item doesn't need your OK.")
        if line.acked_at is not None or line.disputed_at is not None:
            raise ApiError(409, "already_answered", "You've already answered for this item.")
        if body.answer == "ours":
            line.acked_at = now
            event = "line_acked"
        else:
            line.disputed_at = now
            event = "line_disputed"
        service.guest_event(
            ctx,
            now,
            event,
            {
                "line_id": str(line.id),
                "item": line.item_name_snapshot,
                "line_total_paise": line.line_total,
                "staff_user_id": str(line.staff_user_id) if line.staff_user_id else None,
            },
        )
        names = await _staff_names(ctx.session, [line])
        return _line_out(line, order, ctx.tab_session_id, names)

    return await guest_idempotent_write(
        ctx, key, f"POST tabs/{tab_id}/lines/{line_id}/ack", body, LineOut, produce
    )


@router.post("/confirm", responses=ERRORS)
async def confirm_tab(tab_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> ConfirmOut:
    """Waiter-confirm mode: the guest can browse but not order until a waiter
    confirms the table's tab."""
    assert_can(ctx.actor, Capability.OPEN_TRANSFER_MERGE_TABS, ctx.outlet_id)

    async def produce() -> ConfirmOut:
        tab = await ctx.session.scalar(
            select(Tab).where(Tab.id == tab_id, Tab.outlet_id == ctx.outlet_id).with_for_update()
        )
        if tab is None:
            raise not_found("Tab")
        await require_table_access(ctx, tab.table_id)
        if tab.status not in service.LIVE_TAB_STATES:
            raise ApiError(
                409, "tab_not_open", "This tab is already closed.", {"status": tab.status}
            )
        now = clock.utcnow()
        if tab.confirmed_at is None:
            tab.confirmed_at = now
            record_event(
                ctx.session,
                restaurant_id=ctx.restaurant_id,
                tab_id=tab.id,
                at=now,
                actor_type="staff",
                actor_user_id=ctx.actor.user_id,
                event="confirmed",
                table_id=tab.table_id,
            )
        return ConfirmOut(tab_id=tab.id, confirmed_at=tab.confirmed_at)

    return await idempotent_write(
        ctx, key, f"POST tabs/{tab_id}/confirm", None, ConfirmOut, produce
    )
