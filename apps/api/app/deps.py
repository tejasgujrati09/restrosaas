from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.auth import InvalidTokenError, RoleClaim, decode_token
from app.core.permissions import CustomerActor, PermissionDeniedError, Role, StaffActor
from app.db.session import tenant_session
from app.domains.staff.models import StaffRole
from app.domains.tab.models import Tab, TabSession
from app.errors import ApiError
from app.guest_auth import parse_session_token
from app.realtime.hooks import bind_outlet, run_after_commit

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    actor: StaffActor
    claims: list[RoleClaim]


@dataclass(frozen=True)
class OutletContext:
    session: AsyncSession
    actor: StaffActor
    outlet_id: UUID
    restaurant_id: UUID


async def get_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthContext:
    if credentials is None:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    try:
        user_id, claims = decode_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise ApiError(401, "invalid_token", "Your session is not valid. Sign in again.") from exc
    structlog.contextvars.bind_contextvars(actor_user_id=str(user_id))
    actor = StaffActor(
        actor_type="staff",
        user_id=user_id,
        roles=frozenset((c.outlet_id, c.role) for c in claims),
    )
    return AuthContext(actor=actor, claims=claims)


async def get_outlet_context(
    outlet_id: UUID, auth: Annotated[AuthContext, Depends(get_auth)]
) -> AsyncIterator[OutletContext]:
    """Resolves the tenant from the signed claims (never from the request),
    opens a session with `app.restaurant_id` set so Postgres RLS is the
    backstop, then re-reads the user's roles from the database. The token only
    says which tenant to look in; `staff_role` stays the source of truth, so a
    deactivated user loses access on the next request, not when the JWT expires."""
    claim = next((c for c in auth.claims if c.outlet_id == outlet_id), None)
    if claim is None:
        raise PermissionDeniedError(capability=None, outlet_id=outlet_id)
    structlog.contextvars.bind_contextvars(
        restaurant_id=str(claim.restaurant_id), outlet_id=str(outlet_id)
    )
    async with tenant_session(claim.restaurant_id) as session:
        roles = await load_staff_roles(session, auth.actor.user_id, outlet_id)
        bind_outlet(session, outlet_id)
        yield OutletContext(
            session=session,
            actor=StaffActor(
                actor_type="staff",
                user_id=auth.actor.user_id,
                roles=frozenset((outlet_id, r) for r in roles),
            ),
            outlet_id=outlet_id,
            restaurant_id=claim.restaurant_id,
        )
    await run_after_commit(session)


async def load_staff_roles(
    session: AsyncSession, user_id: UUID, outlet_id: UUID
) -> frozenset[Role]:
    """The user's active roles at the outlet, read from the database. Raises
    PermissionDeniedError when there are none (deactivated, or never held any)."""
    db_roles = await session.scalars(
        select(StaffRole.role).where(
            StaffRole.user_id == user_id,
            StaffRole.outlet_id == outlet_id,
            StaffRole.active.is_(True),
        )
    )
    roles = frozenset(Role(r) for r in db_roles)
    if not roles:
        raise PermissionDeniedError(capability=None, outlet_id=outlet_id)
    return roles


@dataclass(frozen=True)
class GuestContext:
    session: AsyncSession
    actor: CustomerActor
    outlet_id: UUID
    restaurant_id: UUID
    tab_id: UUID
    table_id: UUID | None
    tab_session_id: UUID


_SESSION_ENDED = ApiError(
    401, "session_ended", "This table's session has ended. Scan the QR code on your table again."
)


async def get_guest_context(
    outlet_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AsyncIterator[GuestContext]:
    """Guest requests carry a TabSession token, not a staff JWT. The token names
    the tenant; the session must be unexpired, unrevoked and on a live tab, and
    the tab must belong to the outlet in the path. Ownership of a *specific* tab
    is then checked by the handler with `assert_can_write_own_tab`."""
    if credentials is None:
        raise ApiError(401, "not_authenticated", "Scan the QR code on your table to start.")
    try:
        restaurant_id, token_hash = parse_session_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise ApiError(401, "invalid_token", "Scan the QR code on your table again.") from exc
    async with tenant_session(restaurant_id) as session:
        tab_session, tab = await load_guest_session(session, token_hash, outlet_id)
        bind_outlet(session, outlet_id)
        structlog.contextvars.bind_contextvars(
            restaurant_id=str(restaurant_id), outlet_id=str(outlet_id), tab_id=str(tab.id)
        )
        yield GuestContext(
            session=session,
            actor=CustomerActor(
                actor_type="customer", tab_session_id=tab_session.id, tab_id=tab.id
            ),
            outlet_id=outlet_id,
            restaurant_id=restaurant_id,
            tab_id=tab.id,
            table_id=tab.table_id,
            tab_session_id=tab_session.id,
        )
    await run_after_commit(session)


async def load_guest_session(
    session: AsyncSession, token_hash: str, outlet_id: UUID
) -> tuple[TabSession, Tab]:
    """The session must be unexpired, unrevoked and on a live tab of this outlet.
    Raises ApiError 401 when it is over, PermissionDeniedError for another outlet."""
    row = (
        await session.execute(
            select(TabSession, Tab)
            .join(Tab, Tab.id == TabSession.tab_id)
            .where(TabSession.token_hash == token_hash)
        )
    ).first()
    if row is None:
        raise _SESSION_ENDED
    tab_session, tab = row._tuple()
    if (
        tab_session.revoked
        or tab_session.expires_at <= clock.utcnow()
        or tab.status not in ("open", "bill_requested")
    ):
        raise _SESSION_ENDED
    if tab.outlet_id != outlet_id:
        raise PermissionDeniedError(capability=None, outlet_id=outlet_id)
    return tab_session, tab
