"""Which waiters serve which tables. Managers and owners assign; waiters then see only
their tables (`app.domains.tab.access`), in the API and on the live channel."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app import clock
from app.api.v1.common import ERRORS, Ctx, IdempotencyKeyHeader, idempotent_write, not_found
from app.audit import audit
from app.core.permissions import Capability, Role, assert_can
from app.core.realtime import SIGNAL_ASSIGNMENTS_CHANGED
from app.deps import OutletContext
from app.domains.staff.models import AppUser, StaffRole
from app.domains.tab.models import TableAssignment
from app.domains.tenant.models import DiningTable
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
