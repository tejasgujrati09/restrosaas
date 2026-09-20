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


@asynccontextmanager
async def invite_session(token_hash: str) -> AsyncIterator[AsyncSession]:
    """Lets an unauthenticated invitee read exactly the one `staff_invite` row
    whose hash they hold (see the `staff_invite_by_token` policy)."""
    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.invite_token_hash', :h, true)"), {"h": token_hash}
        )
        yield session


@asynccontextmanager
async def qr_session(qr_token: str) -> AsyncIterator[AsyncSession]:
    """Lets an unauthenticated guest read exactly the one `dining_table` row
    whose QR token they hold (see the `dining_table_by_qr_token` policy). Used
    only to learn which restaurant the QR belongs to."""
    async with session_factory() as session, session.begin():
        await session.execute(text("SELECT set_config('app.qr_token', :t, true)"), {"t": qr_token})
        yield session


@asynccontextmanager
async def platform_session(admin_id: UUID) -> AsyncIterator[AsyncSession]:
    """A platform admin's read session: `app.platform_admin_id` unlocks the two SELECT-only
    policies on `restaurant` and `audit_log` (migration 0008), and only while that admin is
    active. Writes to a restaurant never use this; they open `tenant_session` for it."""
    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.platform_admin_id', :aid, true)"), {"aid": str(admin_id)}
        )
        yield session
