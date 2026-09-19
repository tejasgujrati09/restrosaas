"""Writing the append-only `tab_event` log. Every state change on a tab, round or line
goes through here so it is attributed to an actor and reaches the live channel after
commit (CLAUDE.md §3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.tab.models import TabEvent
from app.realtime.hooks import remember_event


@dataclass(frozen=True)
class Actor:
    """Who did it: a guest's TabSession, a staff user, or the system (timers)."""

    actor_type: Literal["customer", "staff", "system"]
    user_id: UUID | None = None
    session_id: UUID | None = None


SYSTEM = Actor("system")


def record_event(
    session: AsyncSession,
    *,
    restaurant_id: UUID,
    tab_id: UUID,
    at: datetime,
    actor_type: str,
    event: str,
    actor_user_id: UUID | None = None,
    actor_session_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    reason: str | None = None,
    table_id: UUID | None = None,
) -> TabEvent:
    row = TabEvent(
        restaurant_id=restaurant_id,
        tab_id=tab_id,
        at=at,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_session_id=actor_session_id,
        event=event,
        payload=payload or {},
        reason=reason,
        table_id=table_id,
    )
    session.add(row)
    remember_event(session, row)
    return row


def emit(
    session: AsyncSession,
    *,
    restaurant_id: UUID,
    tab_id: UUID,
    table_id: UUID | None,
    at: datetime,
    actor: Actor,
    event: str,
    payload: dict[str, Any] | None = None,
    reason: str | None = None,
) -> TabEvent:
    return record_event(
        session,
        restaurant_id=restaurant_id,
        tab_id=tab_id,
        table_id=table_id,
        at=at,
        actor_type=actor.actor_type,
        actor_user_id=actor.user_id,
        actor_session_id=actor.session_id,
        event=event,
        payload=payload,
        reason=reason,
    )
