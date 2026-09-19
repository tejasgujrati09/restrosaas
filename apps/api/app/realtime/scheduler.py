"""Auto-accept a round when its undo window closes, so kitchen and bar screens can
start it and the guest sees "accepted" without anyone having to read the tab.

Durable and shared: a due time per tab goes into a Redis sorted set and every API
replica runs a sweep loop that claims what is due (ZREM, so once). It survives a
restart. Correctness still never depends on it: `accept_due_orders` also runs on
every tab read and is a conditional UPDATE, so a round is accepted, and logged,
exactly once whichever gets there first.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.config import settings
from app.core.state import CUSTOMER_UNDO_WINDOW_SECONDS
from app.db.session import tenant_session
from app.realtime.bus import bus
from app.realtime.hooks import after_commit, bind_outlet, run_after_commit

logger = structlog.get_logger()

# Tests switch scheduling off unless they are about it.
ENABLED = True
SWEEP_INTERVAL_SECONDS = 1.0
# Seconds after placing when the round becomes acceptable (strictly past the undo window).
DELAY_SECONDS: float = CUSTOMER_UNDO_WINDOW_SECONDS + 1


def _key() -> str:
    return f"{settings.redis_key_prefix}:auto_accept"


def schedule_auto_accept(
    session: AsyncSession, restaurant_id: UUID, outlet_id: UUID, tab_id: UUID, placed_at: datetime
) -> None:
    """Records when the round becomes acceptable, once the placing transaction has committed."""
    due = (placed_at + timedelta(seconds=DELAY_SECONDS)).timestamp()

    async def arm() -> None:
        if ENABLED:
            await bus.schedule(_key(), f"{restaurant_id}|{outlet_id}|{tab_id}", due)

    after_commit(session, arm)


async def sweep_once() -> int:
    """Accepts every round whose window has closed. Returns how many tabs were handled."""
    from app.domains.tab.service import accept_due_orders  # avoids an import cycle

    now = clock.utcnow()
    handled = 0
    for member in await bus.claim_due(_key(), now.timestamp()):
        try:
            restaurant, outlet, tab = (UUID(part) for part in member.split("|"))
            async with tenant_session(restaurant) as session:
                bind_outlet(session, outlet)
                await accept_due_orders(session, restaurant, tab, now)
            await run_after_commit(session)
            handled += 1
        except Exception:
            # Dropped, not retried: the tab read path accepts it lazily anyway.
            logger.warning("auto_accept_failed", member=member)
    return handled


async def run_loop() -> None:
    while True:
        try:
            await sweep_once()
        except Exception:
            logger.warning("auto_accept_sweep_failed")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


_loop_task: asyncio.Task[None] | None = None


def start() -> None:
    global _loop_task
    if _loop_task is None:
        _loop_task = asyncio.get_running_loop().create_task(run_loop())


async def cancel_all() -> None:
    global _loop_task
    if _loop_task is not None:
        _loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _loop_task
        _loop_task = None
