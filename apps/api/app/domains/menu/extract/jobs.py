"""Handing extraction to the job queue (Celery, app/worker.py), like `voice/jobs.py`: the API
commits first and queues after. If the queue is down the job stays `queued` and the owner can
press "Try again"; a duplicate message is harmless because the worker claims the row."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import structlog

logger = structlog.get_logger()

Dispatcher = Callable[[UUID, UUID, UUID], None]


def _celery_dispatch(restaurant_id: UUID, outlet_id: UUID, import_id: UUID) -> None:
    from app.worker import celery_app

    celery_app.send_task("menu.extract", args=[str(restaurant_id), str(outlet_id), str(import_id)])


_dispatcher: Dispatcher = _celery_dispatch


def set_dispatcher(dispatcher: Dispatcher | None) -> None:
    global _dispatcher
    _dispatcher = dispatcher or _celery_dispatch


def enqueue(restaurant_id: UUID, outlet_id: UUID, import_id: UUID) -> None:
    try:
        _dispatcher(restaurant_id, outlet_id, import_id)
    except Exception:
        logger.warning("menu_extraction_enqueue_failed", import_id=str(import_id))
