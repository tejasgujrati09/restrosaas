from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.core.permissions import Capability, assert_can
from app.deps import OutletContext, get_outlet_context
from app.domains.staff.models import StaffRole
from app.domains.tenant.models import DiningTable
from app.errors import ErrorOut

router = APIRouter(prefix="/v1/outlets/{outlet_id}", tags=["outlets"])

_errors: dict[int | str, dict[str, Any]] = {401: {"model": ErrorOut}, 403: {"model": ErrorOut}}


class TableOut(BaseModel):
    id: UUID
    label: str
    zone: str
    seats: int
    active: bool


class StaffOut(BaseModel):
    user_id: UUID
    role: str
    active: bool


@router.get("/tables", responses=_errors)
async def list_tables(ctx: Annotated[OutletContext, Depends(get_outlet_context)]) -> list[TableOut]:
    assert_can(ctx.actor, Capability.VIEW_TABLES_AND_TABS, ctx.outlet_id)
    rows = await ctx.session.scalars(
        select(DiningTable)
        .where(DiningTable.outlet_id == ctx.outlet_id)
        .order_by(DiningTable.label)
    )
    return [
        TableOut(id=t.id, label=t.label, zone=t.zone, seats=t.seats, active=t.active) for t in rows
    ]


@router.get("/staff", responses=_errors)
async def list_staff(ctx: Annotated[OutletContext, Depends(get_outlet_context)]) -> list[StaffOut]:
    assert_can(ctx.actor, Capability.MANAGE_WAITER_STAFF, ctx.outlet_id)
    rows = await ctx.session.scalars(
        select(StaffRole).where(StaffRole.outlet_id == ctx.outlet_id).order_by(StaffRole.role)
    )
    return [StaffOut(user_id=s.user_id, role=s.role, active=s.active) for s in rows]
