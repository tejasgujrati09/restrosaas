"""The Celery worker: `uv run celery -A app.worker.celery_app worker` (docs/DECISIONS.md "Voice
provisioning"). Used for the slow, retryable voice platform calls only; the request path never
waits for them. Redis is the broker (the same Redis as the realtime bus, under its own queue)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any
from uuid import UUID

import structlog
from celery import Celery, Task

from app.config import settings
from app.db.session import engine
from app.domains.voice import factory, provisioning
from app.domains.voice.platform import VoicePlatform
from app.realtime.bus import bus

logger = structlog.get_logger()

celery_app = Celery("restosaas", broker=settings.redis_url)
celery_app.conf.update(
    task_default_queue=f"{settings.redis_key_prefix}:jobs",
    task_acks_late=True,  # a job whose worker dies is redelivered; claims make that safe
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # One task at a time in the worker's own process. The jobs are rare and mostly waiting on
    # the voice platform, each runs its own event loop, and the default prefork pool fails to start
    # its children on macOS. Scale by running more workers, not more children.
    worker_pool="solo",
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 300},
    timezone="UTC",
)

MAX_RETRIES = 5
_BACKOFF_SECONDS = (5, 15, 45, 135, 300)


def backoff(retries: int) -> int:
    return _BACKOFF_SECONDS[min(retries, len(_BACKOFF_SECONDS) - 1)]


def _run(coro: Awaitable[provisioning.JobOutcome]) -> provisioning.JobOutcome:
    """Each task runs in its own event loop, so the pooled connections of the last one are
    closed before the loop goes away."""

    async def main() -> provisioning.JobOutcome:
        try:
            return await coro
        finally:
            await engine.dispose()
            await bus.close()

    return asyncio.run(main())


async def _with_platform(
    job: Any, restaurant_id: UUID, outlet_id: UUID, final: bool, **extra: Any
) -> provisioning.JobOutcome:
    platform: VoicePlatform = factory.make_platform()
    try:
        outcome: provisioning.JobOutcome = await job(
            platform, restaurant_id=restaurant_id, outlet_id=outlet_id, final=final, **extra
        )
        return outcome
    finally:
        close = getattr(platform, "aclose", None)
        if close is not None:
            await close()


@celery_app.task(bind=True, name="voice.enable", max_retries=MAX_RETRIES)  # type: ignore[untyped-decorator]
def voice_enable(self: Task, restaurant_id: str, outlet_id: str) -> str:
    outcome = _run(
        _with_platform(
            provisioning.run_enable,
            UUID(restaurant_id),
            UUID(outlet_id),
            self.request.retries >= MAX_RETRIES,
            tools_base_url=factory.tools_base_url(),
            preferred_number=settings.voice_sr_number,
        )
    )
    if outcome == provisioning.JobOutcome.RETRY:
        raise self.retry(countdown=backoff(self.request.retries))
    return str(outcome)


@celery_app.task(bind=True, name="voice.disable", max_retries=MAX_RETRIES)  # type: ignore[untyped-decorator]
def voice_disable(self: Task, restaurant_id: str, outlet_id: str) -> str:
    outcome = _run(
        _with_platform(
            provisioning.run_disable,
            UUID(restaurant_id),
            UUID(outlet_id),
            self.request.retries >= MAX_RETRIES,
        )
    )
    if outcome == provisioning.JobOutcome.RETRY:
        raise self.retry(countdown=backoff(self.request.retries))
    return str(outcome)


@celery_app.task(bind=True, name="menu.extract", max_retries=2)  # type: ignore[untyped-decorator]
def menu_extract(self: Task, restaurant_id: str, outlet_id: str, import_id: str) -> str:
    """Reads an uploaded menu (docs/DECISIONS.md "Menu import from PDF or photos"). Page-level
    failures are handled inside the pipeline and end as a `failed` job the owner can retry; a
    Celery retry is only for the worker itself failing."""
    from app.domains.menu.extract import pipeline
    from app.domains.menu.extract.factory import make_provider
    from app.storage import get_storage

    async def main() -> str:
        provider = make_provider()
        try:
            return await pipeline.run_extraction(
                UUID(restaurant_id), UUID(outlet_id), UUID(import_id), provider, get_storage()
            )
        finally:
            await provider.aclose()
            await engine.dispose()

    try:
        return asyncio.run(main())
    except Exception as exc:
        logger.exception("menu_extraction_worker_error", import_id=import_id)
        raise self.retry(countdown=backoff(self.request.retries), exc=exc) from exc
