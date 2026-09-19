"""Which tables a staff member may see and act on: waiters their assigned tables,
managers and owners all of them. Every waiter-facing read and write goes through
here, so the API (not the UI) is what hides other waiters' tables."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.permissions import Role
from app.deps import OutletContext
from app.domains.tab.models import TableAssignment
from app.errors import ApiError


def sees_all_tables(ctx: OutletContext) -> bool:
    return any(
        outlet == ctx.outlet_id and role in (Role.MANAGER, Role.OWNER)
        for outlet, role in ctx.actor.roles
    )


async def assigned_table_ids(ctx: OutletContext) -> set[UUID]:
    rows = await ctx.session.scalars(
        select(TableAssignment.table_id).where(
            TableAssignment.user_id == ctx.actor.user_id,
            TableAssignment.outlet_id == ctx.outlet_id,
        )
    )
    return set(rows)


async def visible_table_ids(ctx: OutletContext) -> set[UUID] | None:
    """None means every table."""
    return None if sees_all_tables(ctx) else await assigned_table_ids(ctx)


async def require_table_access(
    ctx: OutletContext, table_id: UUID | None, what: str = "Tab"
) -> None:
    """404, not 403: a waiter is not told that someone else's table has a tab on it."""
    if sees_all_tables(ctx):
        return
    if table_id is None or table_id not in await assigned_table_ids(ctx):
        raise ApiError(404, "not_found", f"{what} not found.")
