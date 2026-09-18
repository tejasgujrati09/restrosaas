from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.auth import RoleClaim
from app.core.permissions import Role
from app.db.session import login_session
from app.domains.staff.models import StaffRole


async def load_claims(user_id: UUID) -> list[RoleClaim]:
    """A user's active roles across every restaurant, for the JWT. Uses the
    `staff_role_self_read` policy, so it can only ever see this user's rows."""
    async with login_session(user_id) as session:
        rows = await session.execute(
            select(StaffRole.restaurant_id, StaffRole.outlet_id, StaffRole.role).where(
                StaffRole.user_id == user_id, StaffRole.active.is_(True)
            )
        )
        return [RoleClaim(r.restaurant_id, r.outlet_id, Role(r.role)) for r in rows]
