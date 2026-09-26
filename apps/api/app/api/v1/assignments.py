"""Which waiters serve which tables. Managers and owners assign; waiters then see only
their tables (`app.domains.tab.access`), in the API and on the live channel."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app import clock
from app.api.v1.common import ERRORS, Ctx, IdempotencyKeyHeader, idempotent_write, not_found
from app.api.v1.orders import short_id
from app.audit import audit
from app.core.floor import TableState, table_state
from app.core.permissions import Capability, Role, assert_can
from app.core.realtime import SIGNAL_ASSIGNMENTS_CHANGED
from app.deps import OutletContext
from app.domains.staff.models import AppUser, StaffRole
from app.domains.tab.auto_assign import IN_FLIGHT, LIVE_TAB
from app.domains.tab.models import Order, Tab, TableAssignment
from app.domains.tenant.models import DiningTable, Outlet
from app.errors import ApiError
from app.realtime.hooks import signal

router = APIRouter(prefix="/v1/outlets/{outlet_id}", tags=["assignments"])


class WaiterOut(BaseModel):
    user_id: UUID
    name: str | None
    phone: str


class TableAssignmentOut(BaseModel):
    table_id: UUID
    label: str
    zone: str
    waiters: list[WaiterOut]


class AssigneesIn(BaseModel):
    user_ids: list[UUID] = Field(max_length=50)


class ZoneAssigneesIn(AssigneesIn):
    zone: str = Field(min_length=1, max_length=50)


async def _waiters(ctx: OutletContext, user_ids: list[UUID]) -> None:
    """Only active waiters at this outlet can be assigned."""
    found = set(
        await ctx.session.scalars(
            select(StaffRole.user_id).where(
                StaffRole.outlet_id == ctx.outlet_id,
                StaffRole.role == Role.WAITER.value,
                StaffRole.active.is_(True),
                StaffRole.user_id.in_(user_ids),
            )
        )
    )
    if found != set(user_ids):
        raise ApiError(
            422,
            "not_a_waiter",
            "You can only assign active waiters at this outlet.",
            {"user_ids": [str(u) for u in set(user_ids) - found]},
        )


async def _set(ctx: OutletContext, table_ids: list[UUID], user_ids: list[UUID]) -> None:
    """Makes `user_ids` exactly the waiters of each table."""
    now = clock.utcnow()
    await ctx.session.execute(
        delete(TableAssignment).where(TableAssignment.table_id.in_(table_ids))
    )
    for table_id in table_ids:
        for user_id in dict.fromkeys(user_ids):
            ctx.session.add(
                TableAssignment(
                    restaurant_id=ctx.restaurant_id,
                    outlet_id=ctx.outlet_id,
                    table_id=table_id,
                    user_id=user_id,
                    assigned_by=ctx.actor.user_id,
                    assigned_at=now,
                )
            )
    await ctx.session.flush()
    signal(ctx.session, SIGNAL_ASSIGNMENTS_CHANGED)


async def _listing(ctx: OutletContext) -> list[TableAssignmentOut]:
    tables = (
        await ctx.session.scalars(
            select(DiningTable)
            .where(DiningTable.outlet_id == ctx.outlet_id)
            .order_by(DiningTable.zone, DiningTable.label)
        )
    ).all()
    rows = await ctx.session.execute(
        select(TableAssignment.table_id, AppUser.id, AppUser.name, AppUser.phone)
        .join(AppUser, AppUser.id == TableAssignment.user_id)
        .where(TableAssignment.outlet_id == ctx.outlet_id)
        .order_by(AppUser.name, AppUser.phone)
    )
    by_table: dict[UUID, list[WaiterOut]] = {}
    for table_id, user_id, name, phone in rows:
        by_table.setdefault(table_id, []).append(WaiterOut(user_id=user_id, name=name, phone=phone))
    return [
        TableAssignmentOut(
            table_id=t.id, label=t.label, zone=t.zone, waiters=by_table.get(t.id, [])
        )
        for t in tables
    ]


@router.get("/table-assignments", responses=ERRORS)
async def list_assignments(ctx: Ctx) -> list[TableAssignmentOut]:
    assert_can(ctx.actor, Capability.MANAGE_WAITER_STAFF, ctx.outlet_id)
    return await _listing(ctx)


@router.put("/tables/{table_id}/assignees", responses=ERRORS)
async def assign_table(
    table_id: UUID, ctx: Ctx, key: IdempotencyKeyHeader, body: AssigneesIn
) -> list[TableAssignmentOut]:
    assert_can(ctx.actor, Capability.MANAGE_WAITER_STAFF, ctx.outlet_id)

    async def produce() -> list[TableAssignmentOut]:
        table = await ctx.session.get(DiningTable, table_id)
        if table is None or table.outlet_id != ctx.outlet_id:
            raise not_found("Table")
        await _waiters(ctx, body.user_ids)
        await _set(ctx, [table_id], body.user_ids)
        audit(
            ctx,
            "table.assignees_set",
            "dining_table",
            table_id,
            after={"users": [str(u) for u in body.user_ids]},
        )
        return await _listing(ctx)

    return await idempotent_write(
        ctx, key, f"PUT tables/{table_id}/assignees", body, list[TableAssignmentOut], produce
    )


@router.put("/table-assignments/zone", responses=ERRORS)
async def assign_zone(
    ctx: Ctx, key: IdempotencyKeyHeader, body: ZoneAssigneesIn
) -> list[TableAssignmentOut]:
    """Sets the waiters for every table in a zone in one go, e.g. at the start of a shift."""
    assert_can(ctx.actor, Capability.MANAGE_WAITER_STAFF, ctx.outlet_id)

    async def produce() -> list[TableAssignmentOut]:
        table_ids = list(
            await ctx.session.scalars(
                select(DiningTable.id).where(
                    DiningTable.outlet_id == ctx.outlet_id, DiningTable.zone == body.zone
                )
            )
        )
        if not table_ids:
            raise not_found("Zone")
        await _waiters(ctx, body.user_ids)
        await _set(ctx, table_ids, body.user_ids)
        audit(
            ctx,
            "zone.assignees_set",
            "dining_table",
            None,
            after={"zone": body.zone, "users": [str(u) for u in body.user_ids]},
        )
        return await _listing(ctx)

    return await idempotent_write(
        ctx, key, "PUT table-assignments/zone", body, list[TableAssignmentOut], produce
    )


# ----------------------------------------------------------- board, bulk assign, automatic mode


class BoardWaiterOut(BaseModel):
    user_id: UUID
    name: str | None
    phone: str
    tables: int
    # Tables with a guest at them right now: the "load" the least-loaded strategy uses.
    active_tables: int


class WaitingOrderOut(BaseModel):
    order_id: UUID
    short_id: str
    status: str


class BoardTableOut(BaseModel):
    table_id: UUID
    label: str
    zone: str
    seats: int
    state: TableState
    waiters: list[WaiterOut]
    # True when the system picked the waiter; it lasts until the guest leaves.
    auto_assigned: bool
    # Orders on a table nobody serves: what a manager or host has to hand to a waiter.
    needs_waiter: bool
    waiting_orders: list[WaitingOrderOut]


class AutoAssignConfigOut(BaseModel):
    enabled: bool
    strategy: Literal["nearest", "least_loaded", "rotation"]


class AssignmentBoardOut(BaseModel):
    config: AutoAssignConfigOut
    waiters: list[BoardWaiterOut]
    tables: list[BoardTableOut]


class BulkAssignIn(BaseModel):
    table_ids: list[UUID] = Field(min_length=1, max_length=200)
    user_ids: list[UUID] = Field(max_length=50)


class AutoAssignConfigIn(BaseModel):
    enabled: bool
    strategy: Literal["nearest", "least_loaded", "rotation"]


async def _board(ctx: OutletContext) -> AssignmentBoardOut:
    s = ctx.session
    outlet = await s.get(Outlet, ctx.outlet_id)
    assert outlet is not None
    tables = (
        await s.scalars(
            select(DiningTable)
            .where(DiningTable.outlet_id == ctx.outlet_id, DiningTable.active.is_(True))
            .order_by(DiningTable.zone, DiningTable.label)
        )
    ).all()
    assigned: dict[UUID, list[WaiterOut]] = {}
    auto: set[UUID] = set()
    for table_id, user_id, name, phone, is_auto in await s.execute(
        select(
            TableAssignment.table_id,
            AppUser.id,
            AppUser.name,
            AppUser.phone,
            TableAssignment.auto_assigned,
        )
        .join(AppUser, AppUser.id == TableAssignment.user_id)
        .where(TableAssignment.outlet_id == ctx.outlet_id)
        .order_by(AppUser.name, AppUser.phone)
    ):
        assigned.setdefault(table_id, []).append(WaiterOut(user_id=user_id, name=name, phone=phone))
        if is_auto:
            auto.add(table_id)
    tab_of = {
        t.table_id: t
        for t in await s.scalars(
            select(Tab).where(
                Tab.outlet_id == ctx.outlet_id, Tab.status.in_(LIVE_TAB), Tab.table_id.is_not(None)
            )
        )
    }
    orders_of: dict[UUID, list[Order]] = {}
    if tab_of:
        for order in await s.scalars(
            select(Order).where(Order.tab_id.in_([t.id for t in tab_of.values()]))
        ):
            orders_of.setdefault(order.tab_id, []).append(order)

    cards: list[BoardTableOut] = []
    for table in tables:
        tab = tab_of.get(table.id)
        orders = orders_of.get(tab.id, []) if tab else []
        waiters = assigned.get(table.id, [])
        waiting = [] if waiters else [o for o in orders if o.status in IN_FLIGHT]
        cards.append(
            BoardTableOut(
                table_id=table.id,
                label=table.label,
                zone=table.zone,
                seats=table.seats,
                state=table_state(tab.status if tab else None, [o.status for o in orders]),
                waiters=waiters,
                auto_assigned=table.id in auto,
                needs_waiter=bool(waiting),
                waiting_orders=[
                    WaitingOrderOut(order_id=o.id, short_id=short_id(o.id), status=o.status)
                    for o in sorted(waiting, key=lambda o: o.placed_at)
                ],
            )
        )

    people = await s.execute(
        select(AppUser.id, AppUser.name, AppUser.phone)
        .join(StaffRole, StaffRole.user_id == AppUser.id)
        .where(
            StaffRole.outlet_id == ctx.outlet_id,
            StaffRole.role == Role.WAITER.value,
            StaffRole.active.is_(True),
        )
        .order_by(AppUser.name, AppUser.phone)
    )
    live_tables = {t for t in tab_of if t is not None}
    counts: dict[UUID, tuple[int, int]] = {}
    for table_id, waiters in assigned.items():
        for w in waiters:
            total, active = counts.get(w.user_id, (0, 0))
            counts[w.user_id] = (total + 1, active + (1 if table_id in live_tables else 0))
    return AssignmentBoardOut(
        config=AutoAssignConfigOut(
            enabled=outlet.auto_assign_unassigned_table_orders,
            strategy=outlet.auto_assignment_strategy,  # type: ignore[arg-type]
        ),
        waiters=[
            BoardWaiterOut(
                user_id=uid,
                name=name,
                phone=phone,
                tables=counts.get(uid, (0, 0))[0],
                active_tables=counts.get(uid, (0, 0))[1],
            )
            for uid, name, phone in people
        ],
        tables=cards,
    )


@router.get("/table-assignments/board", responses=ERRORS)
async def assignment_board(ctx: Ctx) -> AssignmentBoardOut:
    """Every table as a card with its state and waiters, the waiters with their load, and the
    automatic-assignment setting: everything the Assign tables screen shows, in one read."""
    assert_can(ctx.actor, Capability.MANAGE_WAITER_STAFF, ctx.outlet_id)
    return await _board(ctx)


@router.put("/table-assignments/bulk", responses=ERRORS)
async def assign_tables_bulk(
    ctx: Ctx, key: IdempotencyKeyHeader, body: BulkAssignIn
) -> AssignmentBoardOut:
    """Makes `user_ids` exactly the waiters of every selected table (an empty list clears them).
    Only assignment changes: tabs, orders and table states are untouched, so nothing in flight
    is disturbed."""
    assert_can(ctx.actor, Capability.MANAGE_WAITER_STAFF, ctx.outlet_id)

    async def produce() -> AssignmentBoardOut:
        table_ids = list(dict.fromkeys(body.table_ids))
        found = await ctx.session.scalar(
            select(func.count())
            .select_from(DiningTable)
            .where(DiningTable.outlet_id == ctx.outlet_id, DiningTable.id.in_(table_ids))
        )
        if found != len(table_ids):
            raise not_found("Table")
        await _waiters(ctx, body.user_ids)
        await _set(ctx, table_ids, body.user_ids)
        audit(
            ctx,
            "tables.assignees_set",
            "dining_table",
            None,
            after={
                "tables": [str(t) for t in table_ids],
                "users": [str(u) for u in body.user_ids],
            },
        )
        return await _board(ctx)

    return await idempotent_write(
        ctx, key, "PUT table-assignments/bulk", body, AssignmentBoardOut, produce
    )


@router.put("/table-assignments/auto", responses=ERRORS)
async def set_auto_assignment(
    ctx: Ctx, key: IdempotencyKeyHeader, body: AutoAssignConfigIn
) -> AssignmentBoardOut:
    """Turns automatic assignment of unassigned-table orders on or off and picks the strategy.
    The strategy is kept while it is off but has no effect."""
    assert_can(ctx.actor, Capability.MANAGE_WAITER_STAFF, ctx.outlet_id)

    async def produce() -> AssignmentBoardOut:
        outlet = await ctx.session.get(Outlet, ctx.outlet_id, with_for_update={"key_share": True})
        assert outlet is not None
        before = {
            "enabled": outlet.auto_assign_unassigned_table_orders,
            "strategy": outlet.auto_assignment_strategy,
        }
        outlet.auto_assign_unassigned_table_orders = body.enabled
        outlet.auto_assignment_strategy = body.strategy
        await ctx.session.flush()
        audit(
            ctx,
            "assignment.auto_changed",
            "outlet",
            ctx.outlet_id,
            before=before,
            after=body.model_dump(),
        )
        return await _board(ctx)

    return await idempotent_write(
        ctx, key, "PUT table-assignments/auto", body, AssignmentBoardOut, produce
    )
