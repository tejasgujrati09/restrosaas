"""Gives a table a waiter when an order arrives at one that has none, if the outlet opted in
(docs/DECISIONS.md "Table assignment: bulk and automatic").

Everything is decided here, in the database transaction that places the order, never from what
a browser last saw. The outlet row is locked first (the same lock invoice numbering uses), so two
orders arriving together decide one after the other: the second sees the first's assignment, its
load and the rotation cursor. If there is no waiter to give, nothing is assigned and the order
stays visible to managers as "needs a waiter" (see `unassigned_tables`); it is never dropped."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.assignment import Strategy, WaiterLoad, choose
from app.core.permissions import Role
from app.core.realtime import SIGNAL_ASSIGNMENTS_CHANGED
from app.domains.staff.models import AppUser, StaffRole
from app.domains.tab.events import SYSTEM, emit
from app.domains.tab.models import Order, Tab, TableAssignment
from app.domains.tenant.models import DiningTable, Outlet
from app.realtime.hooks import signal

logger = structlog.get_logger()

LIVE_TAB = ("open", "bill_requested")
IN_FLIGHT = ("placed", "accepted", "preparing", "ready")


@dataclass(frozen=True)
class AutoAssignResult:
    assigned_to: UUID | None
    # "existing" (table already had a waiter), "disabled", "no_waiter" or "assigned".
    outcome: str


async def release_auto_assignments(session: AsyncSession, table_id: UUID) -> None:
    """Called when a table has no guest any more. Manual assignments stay."""
    await session.execute(
        delete(TableAssignment).where(
            TableAssignment.table_id == table_id, TableAssignment.auto_assigned.is_(True)
        )
    )


async def release_if_vacant(session: AsyncSession, table_id: UUID | None) -> None:
    if table_id is None:
        return
    occupied = await session.scalar(
        select(Tab.id).where(Tab.table_id == table_id, Tab.status.in_(LIVE_TAB)).limit(1)
    )
    if occupied is None:
        await release_auto_assignments(session, table_id)


async def _waiter_loads(session: AsyncSession, outlet_id: UUID, zone: str) -> list[WaiterLoad]:
    waiter_ids = list(
        await session.scalars(
            select(StaffRole.user_id).where(
                StaffRole.outlet_id == outlet_id,
                StaffRole.role == Role.WAITER.value,
                StaffRole.active.is_(True),
            )
        )
    )
    if not waiter_ids:
        return []
    occupied = set(
        await session.scalars(
            select(Tab.table_id).where(
                Tab.outlet_id == outlet_id, Tab.status.in_(LIVE_TAB), Tab.table_id.is_not(None)
            )
        )
    )
    in_flight: dict[UUID, int] = {
        table_id: count
        for table_id, count in await session.execute(
            select(Tab.table_id, func.count(Order.id))
            .join(Order, Order.tab_id == Tab.id)
            .where(
                Tab.outlet_id == outlet_id,
                Tab.status.in_(LIVE_TAB),
                Tab.table_id.is_not(None),
                Order.status.in_(IN_FLIGHT),
            )
            .group_by(Tab.table_id)
        )
        if table_id is not None
    }
    tables: dict[UUID, list[tuple[UUID, str]]] = {}
    for user_id, table_id, table_zone in await session.execute(
        select(TableAssignment.user_id, TableAssignment.table_id, DiningTable.zone)
        .join(DiningTable, DiningTable.id == TableAssignment.table_id)
        .where(TableAssignment.outlet_id == outlet_id, TableAssignment.user_id.in_(waiter_ids))
    ):
        tables.setdefault(user_id, []).append((table_id, table_zone))
    return [
        WaiterLoad(
            user_id=user_id,
            active_tables=sum(1 for t, _ in tables.get(user_id, []) if t in occupied),
            active_orders=sum(in_flight.get(t, 0) for t, _ in tables.get(user_id, [])),
            zone_tables=sum(1 for _, z in tables.get(user_id, []) if z == zone),
        )
        for user_id in waiter_ids
    ]


async def _current_waiter(session: AsyncSession, table_id: UUID) -> UUID | None:
    found: UUID | None = await session.scalar(
        select(TableAssignment.user_id).where(TableAssignment.table_id == table_id).limit(1)
    )
    return found


async def assign_for_new_order(
    session: AsyncSession, *, outlet: Outlet, tab: Tab, order: Order, now: datetime
) -> AutoAssignResult:
    table_id = tab.table_id
    if table_id is None:  # phone and other tab-less orders have no table to assign
        return AutoAssignResult(None, "existing")

    # An automatic assignment made for an earlier guest is not this guest's.
    await session.execute(
        delete(TableAssignment).where(
            TableAssignment.table_id == table_id,
            TableAssignment.auto_assigned.is_(True),
            TableAssignment.assigned_at < tab.opened_at,
        )
    )
    existing = await _current_waiter(session, table_id)
    if existing is not None:
        return AutoAssignResult(existing, "existing")
    if not outlet.auto_assign_unassigned_table_orders:
        return AutoAssignResult(None, "disabled")

    # Serialise decisions for this outlet, then read fresh state: a concurrent order may have
    # just taken this table, changed the settings, or moved the rotation cursor.
    # FOR NO KEY UPDATE: deciders wait for each other, but not for the foreign-key checks that
    # other in-flight orders hold on this row (a plain FOR UPDATE deadlocks with them).
    await session.refresh(outlet, with_for_update={"key_share": True})
    current = await _current_waiter(session, table_id)
    if current is not None:
        return AutoAssignResult(current, "existing")
    if not outlet.auto_assign_unassigned_table_orders:
        return AutoAssignResult(None, "disabled")

    table = await session.get(DiningTable, table_id)
    assert table is not None
    strategy = Strategy(outlet.auto_assignment_strategy)
    waiter = choose(
        strategy,
        await _waiter_loads(session, outlet.id, table.zone),
        outlet.assignment_rotation_last_user_id,
    )
    if waiter is None:
        logger.warning("auto_assign_no_waiter", outlet_id=str(outlet.id), table=table.label)
        signal(session, SIGNAL_ASSIGNMENTS_CHANGED)  # managers' "needs a waiter" list
        return AutoAssignResult(None, "no_waiter")

    session.add(
        TableAssignment(
            restaurant_id=outlet.restaurant_id,
            outlet_id=outlet.id,
            table_id=table_id,
            user_id=waiter,
            assigned_by=None,
            assigned_at=now,
            auto_assigned=True,
        )
    )
    if strategy == Strategy.ROTATION:
        outlet.assignment_rotation_last_user_id = waiter
    name = await session.scalar(select(AppUser.name).where(AppUser.id == waiter))
    await session.flush()
    emit(
        session,
        restaurant_id=outlet.restaurant_id,
        tab_id=tab.id,
        table_id=table_id,
        at=now,
        actor=SYSTEM,
        event="waiter_assigned",
        payload={
            "user_id": str(waiter),
            "waiter": name,
            "table": table.label,
            "order_id": str(order.id),
            "strategy": strategy.value,
            "auto": True,
        },
    )
    signal(session, SIGNAL_ASSIGNMENTS_CHANGED)
    logger.info(
        "table_auto_assigned",
        outlet_id=str(outlet.id),
        table=table.label,
        waiter_id=str(waiter),
        strategy=strategy.value,
    )
    return AutoAssignResult(waiter, "assigned")
