"""The kitchen and bar queue. A ticket shows the moment a round is placed, but Start is
refused until the guest's undo window has closed. No prices anywhere on these screens."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app import clock
from app.api.v1.common import ERRORS, Ctx, IdempotencyKeyHeader, idempotent_write, not_found
from app.core.permissions import Capability, assert_can
from app.core.realtime import SIGNAL_MENU_CHANGED
from app.core.state import CUSTOMER_UNDO_WINDOW_SECONDS, OrderState, TicketState, ticket_startable
from app.deps import OutletContext
from app.domains.menu.models import MenuItem
from app.domains.tab import tickets
from app.domains.tab.models import Order, OrderLine, Tab, Ticket
from app.domains.tenant.models import DiningTable, Station
from app.realtime.hooks import signal

router = APIRouter(prefix="/v1/outlets/{outlet_id}", tags=["kitchen"])

_RECALL_WINDOW = timedelta(hours=1)
_RECALL_LIMIT = 10


class TicketLineOut(BaseModel):
    name: str
    qty: int
    modifiers: list[str]
    note: str | None
    status: str


class TicketOut(BaseModel):
    id: UUID
    status: str
    station_id: UUID | None
    station_name: str | None
    tab_id: UUID
    order_id: UUID
    seq_no: int
    table_label: str | None
    created_at: datetime
    # While set, the guest can still undo the round: show a countdown, Start is locked.
    holding_until: datetime | None
    can_start: bool
    # Where the round came from: customer, waiter or voice. A phone order is locked until a
    # manager or owner accepts it, so it has no countdown.
    source: str
    lines: list[TicketLineOut]


class TicketQueueOut(BaseModel):
    # Queued and preparing tickets, oldest first.
    queue: list[TicketOut]
    # The most recently bumped (ready) tickets, so the last one can be recalled.
    recent: list[TicketOut]


async def _tickets_out(ctx: OutletContext, rows: list[Ticket]) -> list[TicketOut]:
    if not rows:
        return []
    session = ctx.session
    orders = {
        o.id: o
        for o in await session.scalars(
            select(Order).where(Order.id.in_({t.order_id for t in rows}))
        )
    }
    tabs = {
        t.id: t
        for t in await session.scalars(select(Tab).where(Tab.id.in_({t.tab_id for t in rows})))
    }
    labels = {
        table.id: table.label
        for table in await session.scalars(
            select(DiningTable).where(
                DiningTable.id.in_({t.table_id for t in tabs.values() if t.table_id})
            )
        )
    }
    stations = {
        s.id: s.name
        for s in await session.scalars(select(Station).where(Station.outlet_id == ctx.outlet_id))
    }
    lines_by_ticket: dict[UUID, list[OrderLine]] = {}
    for line in await session.scalars(
        select(OrderLine)
        .where(OrderLine.ticket_id.in_([t.id for t in rows]))
        .order_by(OrderLine.position, OrderLine.id)
    ):
        if line.ticket_id:
            lines_by_ticket.setdefault(line.ticket_id, []).append(line)
    out: list[TicketOut] = []
    for ticket in rows:
        order = orders[ticket.order_id]
        tab = tabs[ticket.tab_id]
        # A phone order waits for a person, not a timer: no countdown, and can_start stays false.
        holding = order.status == OrderState.PLACED.value and order.source != "voice"
        out.append(
            TicketOut(
                id=ticket.id,
                status=ticket.status,
                station_id=ticket.station_id,
                station_name=stations.get(ticket.station_id) if ticket.station_id else None,
                tab_id=ticket.tab_id,
                order_id=ticket.order_id,
                seq_no=order.seq_no,
                table_label=labels.get(tab.table_id) if tab.table_id else None,
                created_at=ticket.created_at,
                holding_until=(
                    order.placed_at + timedelta(seconds=CUSTOMER_UNDO_WINDOW_SECONDS)
                    if holding
                    else None
                ),
                can_start=ticket.status == TicketState.QUEUED.value
                and ticket_startable(OrderState(order.status)),
                source=order.source,
                lines=[
                    TicketLineOut(
                        name=line.item_name_snapshot,
                        qty=line.qty,
                        modifiers=[m["name"] for m in line.modifiers_snapshot],
                        note=line.notes,
                        status=line.status,
                    )
                    for line in lines_by_ticket.get(ticket.id, [])
                ],
            )
        )
    return out


@router.get("/tickets", responses=ERRORS)
async def ticket_queue(
    ctx: Ctx, station_id: Annotated[UUID | None, Query()] = None
) -> TicketQueueOut:
    """Oldest first. `station_id` narrows to one station (plus unrouted tickets, which
    every station shows); the screen on a shared tablet picks it, the API does not lock it."""
    assert_can(ctx.actor, Capability.MARK_ORDER_PREPARING, ctx.outlet_id)
    await _accept_due(ctx)
    base = select(Ticket).where(Ticket.outlet_id == ctx.outlet_id)
    if station_id is not None:
        base = base.where((Ticket.station_id == station_id) | Ticket.station_id.is_(None))
    queue = (
        await ctx.session.scalars(
            base.where(Ticket.status.in_(("queued", "preparing"))).order_by(Ticket.created_at)
        )
    ).all()
    recent = (
        await ctx.session.scalars(
            base.where(
                Ticket.status == TicketState.READY.value,
                Ticket.ready_at > clock.utcnow() - _RECALL_WINDOW,
            )
            .order_by(Ticket.ready_at.desc())
            .limit(_RECALL_LIMIT)
        )
    ).all()
    return TicketQueueOut(
        queue=await _tickets_out(ctx, list(queue)), recent=await _tickets_out(ctx, list(recent))
    )


async def _accept_due(ctx: OutletContext) -> None:
    """Auto-accept any round in this outlet whose undo window has closed, so an idle
    queue never shows a stale 'locked' ticket if the sweeper hasn't run yet."""
    from app.domains.tab.service import accept_due_orders

    now = clock.utcnow()
    tab_ids = await ctx.session.scalars(
        select(Order.tab_id)
        .where(Order.outlet_id == ctx.outlet_id, Order.status == OrderState.PLACED.value)
        .distinct()
    )
    for tab_id in tab_ids.all():
        await accept_due_orders(ctx.session, ctx.restaurant_id, tab_id, now)


async def _ticket_out(ctx: OutletContext, ticket: Ticket) -> TicketOut:
    return (await _tickets_out(ctx, [ticket]))[0]


@router.post("/tickets/{ticket_id}/start", responses=ERRORS)
async def start_ticket(ticket_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> TicketOut:
    assert_can(ctx.actor, Capability.MARK_ORDER_PREPARING, ctx.outlet_id)

    async def produce() -> TicketOut:
        await _accept_due(ctx)
        ticket = await tickets.start_ticket(
            ctx.session,
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            ticket_id=ticket_id,
            user_id=ctx.actor.user_id,
            now=clock.utcnow(),
        )
        return await _ticket_out(ctx, ticket)

    return await idempotent_write(
        ctx, key, f"POST tickets/{ticket_id}/start", None, TicketOut, produce
    )


@router.post("/tickets/{ticket_id}/ready", responses=ERRORS)
async def ready_ticket(ticket_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> TicketOut:
    assert_can(ctx.actor, Capability.MARK_ORDER_READY, ctx.outlet_id)

    async def produce() -> TicketOut:
        ticket = await tickets.ready_ticket(
            ctx.session,
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            ticket_id=ticket_id,
            user_id=ctx.actor.user_id,
            now=clock.utcnow(),
        )
        return await _ticket_out(ctx, ticket)

    return await idempotent_write(
        ctx, key, f"POST tickets/{ticket_id}/ready", None, TicketOut, produce
    )


@router.post("/tickets/{ticket_id}/recall", responses=ERRORS)
async def recall_ticket(ticket_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader) -> TicketOut:
    """Brings a bumped ticket back to preparing, if nothing on it has been served yet."""
    assert_can(ctx.actor, Capability.MARK_ORDER_READY, ctx.outlet_id)

    async def produce() -> TicketOut:
        ticket = await tickets.recall_ticket(
            ctx.session,
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            ticket_id=ticket_id,
            user_id=ctx.actor.user_id,
            now=clock.utcnow(),
        )
        return await _ticket_out(ctx, ticket)

    return await idempotent_write(
        ctx, key, f"POST tickets/{ticket_id}/recall", None, TicketOut, produce
    )


class SoldOutIn(BaseModel):
    sold_out: bool


class SoldOutOut(BaseModel):
    item_id: UUID
    name: str
    available: bool


@router.put("/items/{item_id}/sold-out", responses=ERRORS)
async def set_sold_out(
    item_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: SoldOutIn
) -> SoldOutOut:
    """Kitchen and bar mark an item sold out (or back). Guest menus refresh at once and
    waiters are told, through the outlet's `menu_changed` signal."""
    assert_can(ctx.actor, Capability.MARK_ITEM_SOLD_OUT, ctx.outlet_id)

    async def produce() -> SoldOutOut:
        item = await ctx.session.get(MenuItem, item_id)
        if item is None or item.outlet_id != ctx.outlet_id:
            raise not_found("Item")
        item.available = not body.sold_out
        await ctx.session.flush()
        signal(ctx.session, SIGNAL_MENU_CHANGED)
        return SoldOutOut(item_id=item.id, name=item.name, available=item.available)

    return await idempotent_write(
        ctx, key, f"PUT items/{item_id}/sold-out", body, SoldOutOut, produce
    )
