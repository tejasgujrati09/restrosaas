"""Handing provisioning work to the job queue (Celery, app/worker.py).

The API commits a state change (`enable_requested` / `disable_requested`) and only then asks
for the job, so a rolled-back request never queues anything. If the queue is unreachable the
row simply stays requested and the status endpoint queues it again (see `stale_request`), so
losing a message never strands a restaurant. Every job claims its row with a conditional
update, which is what makes a duplicate message harmless.

Tests swap the dispatcher (`set_dispatcher`) and run the job function directly."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from uuid import UUID

import structlog

logger = structlog.get_logger()

JobKind = Literal["enable", "disable"]
Dispatcher = Callable[[JobKind, UUID, UUID, int], None]


def _celery_dispatch(kind: JobKind, restaurant_id: UUID, outlet_id: UUID, delay: int) -> None:
    from app.worker import celery_app

    celery_app.send_task(
        f"voice.{kind}", args=[str(restaurant_id), str(outlet_id)], countdown=delay
    )


_dispatcher: Dispatcher = _celery_dispatch


def set_dispatcher(dispatcher: Dispatcher | None) -> None:
    global _dispatcher
    _dispatcher = dispatcher or _celery_dispatch


def enqueue(kind: JobKind, restaurant_id: UUID, outlet_id: UUID, delay: int = 0) -> None:
    """Best effort: a queue outage must not fail the request that already committed."""
    try:
        _dispatcher(kind, restaurant_id, outlet_id, delay)
    except Exception:
        logger.warning("voice_job_enqueue_failed", kind=kind, outlet_id=str(outlet_id))
