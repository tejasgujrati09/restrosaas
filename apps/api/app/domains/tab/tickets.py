"""Tickets and fulfilment: the kitchen and bar queue, and a waiter marking lines served.

A ticket exists from the moment a round is placed, so a kitchen sees it at once, but it
cannot be started until the round is accepted (`ticket_startable`). Line statuses move
with their ticket; the round's status is derived from its lines by
`derive_order_status`, so the state machines in `app.core.state` stay the only place the
rules live."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.state import (
    OrderState,
    TicketState,
    derive_order_status,
    ticket_startable,
    transition_order,
    transition_ticket,
)
from app.domains.menu.orderable import LoadedItem
from app.domains.tab.events import Actor, emit
from app.domains.tab.models import Order, OrderLine, Tab, Ticket
from app.domains.tenant.models import DiningTable
from app.errors import ApiError

_DONE = ("cancelled", "voided")


async def create_tickets(
    session: AsyncSession,
    restaurant_id: UUID,
    outlet_id: UUID,
    order: Order,
    lines: list[OrderLine],
    loaded: dict[UUID, LoadedItem],
    now: datetime,
) -> list[Ticket]:
    """One ticket per station. Items without a station share one unrouted ticket that
    every kitchen and bar user sees."""
    groups: dict[UUID | None, list[OrderLine]] = {}
    for line in lines:
        groups.setdefault(loaded[line.menu_item_id].row.station_id, []).append(line)
    tickets: list[Ticket] = []
    for station_id, group in groups.items():
        ticket = Ticket(
            restaurant_id=restaurant_id,
            outlet_id=outlet_id,
            order_id=order.id,
            tab_id=order.tab_id,
            station_id=station_id,
            status=TicketState.QUEUED.value,
            created_at=now,
        )
        session.add(ticket)
        await session.flush()
        for line in group:
            line.ticket_id = ticket.id
        tickets.append(ticket)
    await session.flush()
    return tickets


async def cancel_order_tickets(session: AsyncSession, order_id: UUID) -> None:
    await session.execute(
        update(Ticket)
        .where(Ticket.order_id == order_id, Ticket.status != TicketState.CANCELLED.value)
        .values(status=TicketState.CANCELLED.value)
    )


async def _tab(session: AsyncSession, tab_id: UUID) -> Tab:
    tab = await session.get(Tab, tab_id)
    assert tab is not None
    return tab


def _log(
    session: AsyncSession,
    restaurant_id: UUID,
    tab: Tab,
    now: datetime,
    user_id: UUID,
    event: str,
    payload: dict[str, Any],
) -> None:
    emit(
        session,
        restaurant_id=restaurant_id,
        tab_id=tab.id,
        table_id=tab.table_id,
        at=now,
        actor=Actor("staff", user_id=user_id),
        event=event,
        payload=payload,
    )


async def sync_order_status(
    session: AsyncSession, restaurant_id: UUID, order: Order, tab: Tab, now: datetime, user_id: UUID
) -> None:
    """Moves the round to where its lines say it is, logging the change."""
    statuses = list(
        await session.scalars(select(OrderLine.status).where(OrderLine.order_id == order.id))
    )
    current = OrderState(order.status)
    target = derive_order_status(current, statuses)
    if target == current:
        return
    order.status = transition_order(current, target).value
    _log(
        session,
        restaurant_id,
        tab,
        now,
        user_id,
        f"order_{target.value}",
        {"order_id": str(order.id), "seq_no": order.seq_no},
    )


async def _locked_ticket(session: AsyncSession, outlet_id: UUID, ticket_id: UUID) -> Ticket:
    ticket = await session.scalar(
        select(Ticket)
        .where(Ticket.id == ticket_id, Ticket.outlet_id == outlet_id)
        .with_for_update()
    )
    if ticket is None:
        raise ApiError(404, "not_found", "Ticket not found.")
    return ticket


async def _payload(session: AsyncSession, ticket: Ticket, order: Order, tab: Tab) -> dict[str, Any]:
    table = await session.get(DiningTable, tab.table_id) if tab.table_id else None
    return {
        "ticket_id": str(ticket.id),
        "order_id": str(order.id),
        "seq_no": order.seq_no,
        "station_id": str(ticket.station_id) if ticket.station_id else None,
        "table": table.label if table else None,
    }


async def _move_ticket(
    session: AsyncSession,
    *,
    restaurant_id: UUID,
    outlet_id: UUID,
    ticket_id: UUID,
    user_id: UUID,
    now: datetime,
    target: TicketState,
    line_from: str,
    line_to: str,
    event: str,
) -> Ticket:
    ticket = await _locked_ticket(session, outlet_id, ticket_id)
    order = await session.get(Order, ticket.order_id)
    assert order is not None
    tab = await _tab(session, ticket.tab_id)
    if target == TicketState.PREPARING and not ticket_startable(OrderState(order.status)):
        raise ApiError(
            409,
            "undo_window_open",
            "The guest can still undo this order. It can be started in a moment.",
            {"order_status": order.status},
        )
    if target == TicketState.PREPARING and ticket.status == TicketState.READY.value:
        served = await session.scalar(
            select(OrderLine.id).where(
                OrderLine.ticket_id == ticket.id, OrderLine.status == "served"
            )
        )
        if served is not None:
            raise ApiError(409, "already_served", "Part of this ticket has already been served.")
    ticket.status = transition_ticket(TicketState(ticket.status), target).value
    if target == TicketState.PREPARING and line_from == "accepted":
        ticket.started_at, ticket.started_by = now, user_id
    if target == TicketState.READY:
        ticket.ready_at, ticket.ready_by = now, user_id
    await session.execute(
        update(OrderLine)
        .where(OrderLine.ticket_id == ticket.id, OrderLine.status == line_from)
        .values(status=line_to)
    )
    _log(
        session,
        restaurant_id,
        tab,
        now,
        user_id,
        event,
        await _payload(session, ticket, order, tab),
    )
    await sync_order_status(session, restaurant_id, order, tab, now, user_id)
    return ticket


async def start_ticket(
    session: AsyncSession,
    *,
    restaurant_id: UUID,
    outlet_id: UUID,
    ticket_id: UUID,
    user_id: UUID,
    now: datetime,
) -> Ticket:
    return await _move_ticket(
        session,
        restaurant_id=restaurant_id,
        outlet_id=outlet_id,
        ticket_id=ticket_id,
        user_id=user_id,
        now=now,
        target=TicketState.PREPARING,
        line_from="accepted",
        line_to="preparing",
        event="ticket_started",
    )


async def ready_ticket(
    session: AsyncSession,
    *,
    restaurant_id: UUID,
    outlet_id: UUID,
    ticket_id: UUID,
    user_id: UUID,
    now: datetime,
) -> Ticket:
    return await _move_ticket(
        session,
        restaurant_id=restaurant_id,
        outlet_id=outlet_id,
        ticket_id=ticket_id,
        user_id=user_id,
        now=now,
        target=TicketState.READY,
        line_from="preparing",
        line_to="ready",
        event="ticket_ready",
    )


async def recall_ticket(
    session: AsyncSession,
    *,
    restaurant_id: UUID,
    outlet_id: UUID,
    ticket_id: UUID,
    user_id: UUID,
    now: datetime,
) -> Ticket:
    return await _move_ticket(
        session,
        restaurant_id=restaurant_id,
        outlet_id=outlet_id,
        ticket_id=ticket_id,
        user_id=user_id,
        now=now,
        target=TicketState.PREPARING,
        line_from="ready",
        line_to="preparing",
        event="ticket_recalled",
    )


async def serve_lines(
    session: AsyncSession,
    *,
    restaurant_id: UUID,
    tab: Tab,
    order_id: UUID,
    line_ids: list[UUID] | None,
    user_id: UUID,
    now: datetime,
) -> Order:
    """Marks ready lines served: the ones named, or every ready line in the round.
    Only ready lines can be served (409 `not_ready` otherwise)."""
    order = await session.scalar(
        select(Order).where(Order.id == order_id, Order.tab_id == tab.id).with_for_update()
    )
    if order is None:
        raise ApiError(404, "not_found", "Order not found.")
    lines = list(
        await session.scalars(
            select(OrderLine)
            .where(OrderLine.order_id == order.id)
            .order_by(OrderLine.position, OrderLine.id)
        )
    )
    chosen = [line for line in lines if line_ids is None or line.id in line_ids]
    if line_ids is not None and len(chosen) != len(set(line_ids)):
        raise ApiError(404, "not_found", "Line not found.")
    if line_ids is None:
        # "Serve what's ready": fine while some lines are still cooking, but a round with
        # nothing ready (and something still to make) has nothing to serve yet.
        pending = [line for line in chosen if line.status not in ("ready", "served", *_DONE)]
        if pending and not any(line.status == "ready" for line in chosen):
            raise ApiError(
                409,
                "not_ready",
                "That isn't ready yet.",
                {"line_ids": [str(line.id) for line in pending]},
            )
    else:
        unready = [line for line in chosen if line.status not in ("ready", "served")]
        if unready:
            raise ApiError(
                409,
                "not_ready",
                "That item isn't ready yet.",
                {"line_ids": [str(line.id) for line in unready]},
            )
    served = [line for line in chosen if line.status == "ready"]
    for line in served:
        line.status = "served"
        line.served_at, line.served_by = now, user_id
        _log(
            session,
            restaurant_id,
            tab,
            now,
            user_id,
            "line_served",
            {"order_id": str(order.id), "line_id": str(line.id), "item": line.item_name_snapshot},
        )
    await session.flush()
    for ticket_id in {line.ticket_id for line in served if line.ticket_id}:
        remaining = await session.scalar(
            select(OrderLine.id).where(
                OrderLine.ticket_id == ticket_id, OrderLine.status.not_in(("served", *_DONE))
            )
        )
        ticket = await session.get(Ticket, ticket_id)
        if remaining is None and ticket is not None and ticket.status == TicketState.READY.value:
            ticket.status = transition_ticket(TicketState.READY, TicketState.BUMPED).value
            ticket.bumped_by = user_id
    await sync_order_status(session, restaurant_id, order, tab, now, user_id)
    return order
