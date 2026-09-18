"""Auto-accept a round when its undo window closes, so kitchen and bar screens
hear about it without anyone having to read the tab.

Best effort: timers live in this process and are lost on restart. Correctness
never depends on them, because `accept_due_orders` also runs on every tab read
and is a conditional UPDATE, so a round is accepted, and logged, exactly once.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.core.state import CUSTOMER_UNDO_WINDOW_SECONDS
from app.db.session import tenant_session
from app.realtime.hooks import after_commit, bind_outlet, run_after_commit

logger = structlog.get_logger()

# Tests switch timers off (or shrink the delay) so no timer outlives its test.
ENABLED = True
DELAY_SECONDS: float = CUSTOMER_UNDO_WINDOW_SECONDS + 1

_pending: set[asyncio.Task[None]] = set()


async def _accept_later(restaurant_id: UUID, outlet_id: UUID, tab_id: UUID, delay: float) -> None:
    await asyncio.sleep(delay)
    from app.domains.tab.service import accept_due_orders  # avoids an import cycle

    try:
        async with tenant_session(restaurant_id) as session:
            bind_outlet(session, outlet_id)
            await accept_due_orders(session, restaurant_id, tab_id, clock.utcnow())
        await run_after_commit(session)
    except Exception:
        logger.warning("auto_accept_timer_failed", tab_id=str(tab_id))


def schedule_auto_accept(
    session: AsyncSession, restaurant_id: UUID, outlet_id: UUID, tab_id: UUID
) -> None:
    """Arms the timer once the placing transaction has committed."""

    async def arm() -> None:
        if not ENABLED:
            return
        task = asyncio.get_running_loop().create_task(
            _accept_later(restaurant_id, outlet_id, tab_id, DELAY_SECONDS)
        )
        _pending.add(task)
        task.add_done_callback(_pending.discard)

    after_commit(session, arm)


async def cancel_all() -> None:
    for task in list(_pending):
        task.cancel()
    await asyncio.gather(*_pending, return_exceptions=True)
