from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def tenant_session(restaurant_id: UUID) -> AsyncIterator[AsyncSession]:
    """One transaction with `app.restaurant_id` set for Postgres RLS.

    `set_config(..., true)` is the transaction-local form (`SET LOCAL`) that
    accepts a bind parameter.
    """
    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.restaurant_id', :rid, true)"),
            {"rid": str(restaurant_id)},
        )
        yield session


@asynccontextmanager
async def login_session(user_id: UUID) -> AsyncIterator[AsyncSession]:
    """Used only after OTP verification, to read the user's own staff roles
    across restaurants (see the `staff_role_self_read` policy)."""
    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.user_id', :uid, true)"),
            {"uid": str(user_id)},
        )
        yield session


@asynccontextmanager
async def anonymous_session() -> AsyncIterator[AsyncSession]:
    """No tenant context: RLS-protected tables return zero rows. For global
    tables such as `app_user` only."""
    async with session_factory() as session, session.begin():
        yield session
