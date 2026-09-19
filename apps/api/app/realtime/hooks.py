"""Work that must happen only after a request's transaction has committed:
telling connected clients what changed, and arming timers. Rolled-back work
never reaches this point, so nobody hears about it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.tab.models import TabEvent
from app.realtime.bus import bus, outlet_channel

logger = structlog.get_logger()

_EVENTS = "tab_events"
_CALLBACKS = "after_commit"
_OUTLET = "outlet_id"


def bind_outlet(session: AsyncSession, outlet_id: UUID) -> None:
    session.info[_OUTLET] = outlet_id


def remember_event(session: AsyncSession, row: TabEvent) -> None:
    session.info.setdefault(_EVENTS, []).append(row)


def after_commit(session: AsyncSession, callback: Callable[[], Awaitable[None]]) -> None:
    session.info.setdefault(_CALLBACKS, []).append(callback)


def signal(session: AsyncSession, name: str) -> None:
    """An outlet-wide nudge with no tab attached ("the menu changed", "assignments
    changed"), sent after commit like events. Asking twice in one request sends once."""
    sent: set[str] = session.info.setdefault("signals", set())
    if name in sent:
        return
    sent.add(name)

    async def send() -> None:
        outlet_id: UUID | None = session.info.get(_OUTLET)
        if outlet_id is not None:
            await bus.publish(outlet_channel(outlet_id), {"kind": "signal", "name": name})

    after_commit(session, send)


def event_message(row: TabEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "tab_id": str(row.tab_id),
        "at": row.at.isoformat(),
        "event": row.event,
        "actor_type": row.actor_type,
        "table_id": str(row.table_id) if row.table_id else None,
        "payload": row.payload,
    }


async def run_after_commit(session: AsyncSession) -> None:
    """Best effort by design: the commit already happened, so a Redis outage must
    not fail the request. Clients recover missed events by resuming from the database."""
    outlet_id: UUID | None = session.info.get(_OUTLET)
    if outlet_id is not None:
        for row in session.info.get(_EVENTS, []):
            try:
                await bus.publish(outlet_channel(outlet_id), event_message(row))
            except Exception:
                logger.warning("realtime_publish_failed", tab_event=row.event, tab_event_id=row.id)
    for callback in session.info.get(_CALLBACKS, []):
        try:
            await callback()
        except Exception:
            logger.warning("after_commit_callback_failed")
    session.info.pop("signals", None)
    session.info.pop(_EVENTS, None)
    session.info.pop(_CALLBACKS, None)
