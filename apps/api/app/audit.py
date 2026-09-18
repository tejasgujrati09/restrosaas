from __future__ import annotations

from typing import Any
from uuid import UUID

from app.deps import OutletContext
from app.domains.staff.models import AuditLog


def audit(
    ctx: OutletContext,
    action: str,
    target_type: str,
    target_id: UUID | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    ctx.session.add(
        AuditLog(
            actor_user_id=ctx.actor.user_id,
            restaurant_id=ctx.restaurant_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
        )
    )
