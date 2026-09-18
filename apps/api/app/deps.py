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

from app.auth import InvalidTokenError, RoleClaim, decode_token
from app.core.permissions import PermissionDeniedError, Role, StaffActor
from app.db.session import tenant_session
from app.domains.staff.models import StaffRole
from app.errors import ApiError

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
        db_roles = await session.scalars(
            select(StaffRole.role).where(
                StaffRole.user_id == auth.actor.user_id,
                StaffRole.outlet_id == outlet_id,
                StaffRole.active.is_(True),
            )
        )
        roles = frozenset((outlet_id, Role(r)) for r in db_roles)
        if not roles:
            raise PermissionDeniedError(capability=None, outlet_id=outlet_id)
        yield OutletContext(
            session=session,
            actor=StaffActor(actor_type="staff", user_id=auth.actor.user_id, roles=roles),
            outlet_id=outlet_id,
            restaurant_id=claim.restaurant_id,
        )
