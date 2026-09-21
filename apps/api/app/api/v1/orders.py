"""The owner's Orders screen: every order for the outlet, whatever its source, grouped into
the tabs an owner thinks in, with counts and a real timeline (docs/DECISIONS.md "Owner Orders
screen"). Read-only. Changing an order still goes through the existing endpoints (accept or
reject a phone order, mark a ready round served), each of which enforces its own rules and
roles; this screen only says which of them are worth offering.

Counts and the list use the same date window (in the outlet's timezone), so a tab's number is
always the number of rows behind it. Orders still open from before that window are counted
separately, never mixed in and never hidden."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Query
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy import Select, String, cast, func, or_, select

from app import clock
from app.api.v1.common import ERRORS, Ctx
from app.core.order_view import (
    OPEN_STATES,
    OrderAction,
    OrderGroup,
    available_actions,
    group_of,
    statuses_in,
)
from app.core.permissions import Capability, PermissionDeniedError, assert_can
from app.core.tab_totals import TotalsLine, compute_tab_totals
from app.domains.staff.models import AppUser
from app.domains.tab.models import Order, OrderLine, Tab, TabEvent, Ticket
from app.domains.tenant.models import DiningTable, Outlet, Station
from app.domains.voice.models import Customer
from app.errors import ApiError

router = APIRouter(prefix="/v1/outlets/{outlet_id}/staff/orders", tags=["orders"])

_MAX_RANGE_DAYS = 92
_PAGE = 50
_SOURCES = ("customer", "waiter", "voice", "aggregator")


class OrderItemOut(BaseModel):
    name: str
    qty: int


class OrderRowOut(BaseModel):
    id: UUID
    short_id: str
    status: str
    group: OrderGroup
    source: str
    fulfillment_type: str
    placed_at: datetime
    table_label: str | None
    customer_name: str | None
    customer_phone: str | None
    items: list[OrderItemOut]
    total_paise: int


class OrderCountsOut(BaseModel):
    new: int
    in_progress: int
    ready: int
    completed: int
    cancelled: int


class OrdersOut(BaseModel):
    date_from: date
    date_to: date
    counts: OrderCountsOut
    # Orders still waiting on someone that were placed before `date_from`.
    earlier_open: int
    orders: list[OrderRowOut]
    has_more: bool


class OrderLineOut(BaseModel):
    name: str
    qty: int
    unit_price_paise: int
    modifiers: list[str]
    notes: str | None
    line_total_paise: int
    status: str
    void_reason: str | None


class TimelineEntryOut(BaseModel):
    at: datetime
    label: str
    by: str | None
    reason: str | None


class OrderTicketOut(BaseModel):
    station: str | None
    status: str
    started_at: datetime | None
    ready_at: datetime | None


class PricingOut(BaseModel):
    # True when the item prices already contain the taxes below (they are not added on top).
    taxes_included: bool
    items_paise: int
    cgst_paise: int
    sgst_paise: int
    liquor_vat_paise: int
    service_charge_paise: int
    estimated_total_paise: int


class OrderDetailOut(BaseModel):
    id: UUID
    short_id: str
    tab_id: UUID
    status: str
    group: OrderGroup
    source: str
    fulfillment_type: str
    placed_at: datetime
    table_label: str | None
    customer_name: str | None
    customer_phone: str | None
    delivery_address: str | None
    call_id: str | None
    tab_status: str
    lines: list[OrderLineOut]
    pricing: PricingOut
    tickets: list[OrderTicketOut]
    timeline: list[TimelineEntryOut]
    actions: list[OrderAction]


def short_id(order_id: UUID) -> str:
    """No sequential order number exists (see docs/DECISIONS.md), so the first characters of
    the id stand in: short, stable, and searchable."""
    return order_id.hex[:6].upper()


def _window(
    tz: ZoneInfo, date_from: date | None, date_to: date | None
) -> tuple[date, date, datetime, datetime]:
    today = clock.utcnow().astimezone(tz).date()
    start, end = date_from or today, date_to or date_from or today
    if end < start:
        raise ApiError(422, "validation_error", "The end date is before the start date.")
    if (end - start).days >= _MAX_RANGE_DAYS:
        raise ApiError(422, "validation_error", "Choose a range of three months or less.")
    lo = datetime.combine(start, time.min, tzinfo=tz).astimezone(UTC)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end, lo, hi


def _filters(
    stmt: Select[Any],
    ctx: Ctx,
    *,
    source: str | None,
    table_id: UUID | None,
    placed_by: UUID | None,
    q: str | None,
) -> Select[Any]:
    stmt = stmt.where(Order.outlet_id == ctx.outlet_id)
    if source:
        stmt = stmt.where(Order.source == source)
    if table_id:
        stmt = stmt.where(Tab.table_id == table_id)
    if placed_by:
        stmt = stmt.where(Order.placed_by_user_id == placed_by)
    if q and q.strip():
        term = q.strip().lstrip("#")
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                cast(Order.id, String).ilike(f"{term.lower()}%"),
                Customer.name.ilike(like),
                Customer.phone.ilike(like),
                Tab.customer_phone.ilike(like),
                DiningTable.label.ilike(like),
            )
        )
    return stmt


def _base() -> Select[Any]:
    return (
        select(Order)
        .join(Tab, Tab.id == Order.tab_id)
        .join(Customer, Customer.id == Order.customer_id, isouter=True)
        .join(DiningTable, DiningTable.id == Tab.table_id, isouter=True)
    )


@router.get("", responses=ERRORS)
async def list_orders(
    ctx: Ctx,
    group: OrderGroup = OrderGroup.NEW,
    source: Annotated[Literal["customer", "waiter", "voice", "aggregator"] | None, Query()] = None,
    table_id: UUID | None = None,
    placed_by: UUID | None = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrdersOut:
    assert_can(ctx.actor, Capability.VIEW_ORDERS, ctx.outlet_id)
    outlet = await ctx.session.get(Outlet, ctx.outlet_id)
    assert outlet is not None
    tz = ZoneInfo(outlet.timezone)
    start, end, lo, hi = _window(tz, date_from, date_to)
    scoped = _filters(_base(), ctx, source=source, table_id=table_id, placed_by=placed_by, q=q)
    windowed = scoped.where(Order.placed_at >= lo, Order.placed_at < hi)

    counted = windowed.with_only_columns(Order.status, func.count()).group_by(Order.status)
    per_group = dict.fromkeys(OrderGroup, 0)
    for status, n in (await ctx.session.execute(counted)).all():
        per_group[group_of(status)] += n
    earlier = await ctx.session.scalar(
        scoped.where(Order.placed_at < lo, Order.status.in_([s.value for s in OPEN_STATES]))
        .with_only_columns(func.count())
        .order_by(None)
    )

    page = (
        await ctx.session.scalars(
            windowed.where(Order.status.in_(statuses_in(group)))
            .order_by(Order.placed_at.desc(), Order.id)
            .offset(offset)
            .limit(_PAGE + 1)
        )
    ).all()
    has_more = len(page) > _PAGE
    return OrdersOut(
        date_from=start,
        date_to=end,
        counts=OrderCountsOut(**{g.value: n for g, n in per_group.items()}),
        earlier_open=earlier or 0,
        orders=await _rows(ctx, list(page[:_PAGE])),
        has_more=has_more,
    )


async def _rows(ctx: Ctx, orders: list[Order]) -> list[OrderRowOut]:
    if not orders:
        return []
    ids = [o.id for o in orders]
    lines: dict[UUID, list[OrderLine]] = {}
    for line in await ctx.session.scalars(
        select(OrderLine)
        .where(OrderLine.order_id.in_(ids), OrderLine.voided_at.is_(None))
        .order_by(OrderLine.position, OrderLine.id)
    ):
        lines.setdefault(line.order_id, []).append(line)
    tabs = {
        t.id: t
        for t in await ctx.session.scalars(
            select(Tab).where(Tab.id.in_({o.tab_id for o in orders}))
        )
    }
    labels = {
        t.id: t.label
        for t in await ctx.session.scalars(
            select(DiningTable).where(
                DiningTable.id.in_({t.table_id for t in tabs.values() if t.table_id})
            )
        )
    }
    customers = {
        c.id: c
        for c in await ctx.session.scalars(
            select(Customer).where(
                Customer.id.in_({o.customer_id for o in orders if o.customer_id})
            )
        )
    }
    rows: list[OrderRowOut] = []
    for order in orders:
        tab = tabs[order.tab_id]
        customer = customers.get(order.customer_id) if order.customer_id else None
        mine = lines.get(order.id, [])
        rows.append(
            OrderRowOut(
                id=order.id,
                short_id=short_id(order.id),
                status=order.status,
                group=group_of(order.status),
                source=order.source,
                fulfillment_type=order.fulfillment_type,
                placed_at=order.placed_at,
                table_label=labels.get(tab.table_id) if tab.table_id else None,
                customer_name=customer.name if customer else None,
                customer_phone=customer.phone if customer else tab.customer_phone,
                items=[OrderItemOut(name=x.item_name_snapshot, qty=x.qty) for x in mine],
                total_paise=sum(x.line_total for x in mine),
            )
        )
    return rows


_LABELS = {
    "order_placed": "Order received",
    "order_accepted": "Accepted",
    "order_preparing": "Preparing",
    "order_ready": "Ready",
    "order_served": "Served",
    "order_dispatched": "Sent out for delivery",
    "order_delivered": "Delivered",
    "order_cancelled": "Cancelled",
}


@router.get("/{order_id}", responses=ERRORS)
async def get_order(order_id: UUID, ctx: Ctx) -> OrderDetailOut:
    assert_can(ctx.actor, Capability.VIEW_ORDERS, ctx.outlet_id)
    order = await ctx.session.scalar(
        select(Order).where(Order.id == order_id, Order.outlet_id == ctx.outlet_id)
    )
    if order is None:
        raise ApiError(404, "not_found", "Order not found.")
    outlet = await ctx.session.get(Outlet, ctx.outlet_id)
    tab = await ctx.session.get(Tab, order.tab_id)
    assert outlet is not None and tab is not None
    table = await ctx.session.get(DiningTable, tab.table_id) if tab.table_id else None
    customer = await ctx.session.get(Customer, order.customer_id) if order.customer_id else None
    lines = list(
        await ctx.session.scalars(
            select(OrderLine)
            .where(OrderLine.order_id == order.id)
            .order_by(OrderLine.position, OrderLine.id)
        )
    )
    live = [x for x in lines if x.voided_at is None]
    totals = compute_tab_totals(
        [
            TotalsLine(
                unit_gross_paise=x.line_total // x.qty,
                qty=x.qty,
                rate_bp=x.tax_class_snapshot["rate_bp"],
                is_liquor=x.tax_class_snapshot["is_liquor"],
                prices_include_tax=x.tax_class_snapshot["prices_include_tax"],
            )
            for x in live
            if x.qty
        ],
        service_charge_bp=outlet.service_charge_bp,
        service_charge_removed=tab.service_charge_removed,
    )
    tickets = list(
        await ctx.session.scalars(
            select(Ticket).where(Ticket.order_id == order.id).order_by(Ticket.created_at)
        )
    )
    stations = {
        s.id: s.name
        for s in await ctx.session.scalars(
            select(Station).where(Station.id.in_({t.station_id for t in tickets if t.station_id}))
        )
    }
    events = list(
        await ctx.session.scalars(
            select(TabEvent)
            .where(
                TabEvent.tab_id == tab.id,
                TabEvent.payload["order_id"].astext == str(order.id),
                TabEvent.event.in_(list(_LABELS)),
            )
            .order_by(TabEvent.at, TabEvent.id)
        )
    )
    names = {
        u.id: u.name
        for u in await ctx.session.scalars(
            select(AppUser).where(
                AppUser.id.in_({e.actor_user_id for e in events if e.actor_user_id})
            )
        )
    }

    def can(capability: Capability) -> bool:
        try:
            assert_can(ctx.actor, capability, ctx.outlet_id)
        except PermissionDeniedError:
            return False
        return True

    return OrderDetailOut(
        id=order.id,
        short_id=short_id(order.id),
        tab_id=tab.id,
        status=order.status,
        group=group_of(order.status),
        source=order.source,
        fulfillment_type=order.fulfillment_type,
        placed_at=order.placed_at,
        table_label=table.label if table else None,
        customer_name=customer.name if customer else None,
        customer_phone=customer.phone if customer else tab.customer_phone,
        delivery_address=order.delivery_address_snapshot,
        call_id=order.external_call_id,
        tab_status=tab.status,
        lines=[
            OrderLineOut(
                name=x.item_name_snapshot,
                qty=x.qty,
                unit_price_paise=x.line_total // x.qty if x.qty else x.unit_price_snapshot,
                modifiers=[str(m.get("name", "")) for m in x.modifiers_snapshot if m.get("name")],
                notes=x.notes,
                line_total_paise=x.line_total,
                status=x.status,
                void_reason=x.void_reason if x.voided_at else None,
            )
            for x in lines
        ],
        pricing=PricingOut(
            taxes_included=all(x.tax_class_snapshot["prices_include_tax"] for x in live),
            items_paise=totals.items_paise,
            cgst_paise=totals.cgst_paise,
            sgst_paise=totals.sgst_paise,
            liquor_vat_paise=totals.liquor_vat_paise,
            service_charge_paise=totals.service_charge_paise,
            estimated_total_paise=totals.estimated_total_paise,
        ),
        tickets=[
            OrderTicketOut(
                station=stations.get(t.station_id) if t.station_id else None,
                status=t.status,
                started_at=t.started_at,
                ready_at=t.ready_at,
            )
            for t in tickets
        ],
        timeline=_timeline(order, events, names),
        actions=available_actions(
            order.status,
            order.source,
            can_accept_voice=can(Capability.ACCEPT_VOICE_ORDERS),
            can_serve=can(Capability.MARK_ORDER_SERVED),
        ),
    )


def _timeline(
    order: Order, events: list[TabEvent], names: dict[UUID, str | None]
) -> list[TimelineEntryOut]:
    """Only moments that are on record. The order's own `placed_at` opens it if the placed
    event is missing; nothing is inferred or filled in."""
    entries: list[TimelineEntryOut] = []
    if not any(e.event == "order_placed" for e in events):
        entries.append(
            TimelineEntryOut(at=order.placed_at, label="Order received", by=None, reason=None)
        )
    for e in events:
        label = _LABELS[e.event]
        if e.event == "order_accepted":
            label = "Accepted automatically" if e.payload.get("auto") else "Accepted by staff"
        by = names.get(e.actor_user_id) if e.actor_user_id else None
        if by is None and e.actor_type == "customer":
            by = "Guest"
        if by is None and e.actor_type == "system":
            by = "Phone agent" if order.source == "voice" else "System"
        entries.append(TimelineEntryOut(at=e.at, label=label, by=by, reason=e.reason))
    return entries
