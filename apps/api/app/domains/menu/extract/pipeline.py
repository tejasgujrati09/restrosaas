"""Runs one import job: read the stored files, extract page by page, merge, and leave draft rows
for the owner to review. Runs in the worker; the request path never waits for it.

No database transaction is held while a page is with the model: each step is its own short
tenant session, so progress is visible to the status endpoint and a crash loses at most one page.
Only pages that have not succeeded are sent, so a retry never repeats paid work."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from pydantic import ValidationError
from sqlalchemy import select, update

from app import clock
from app.config import settings
from app.db.session import tenant_session
from app.domains.menu.extract.files import FileProblem, load_pages
from app.domains.menu.extract.normalize import rows_from_pages
from app.domains.menu.extract.provider import (
    MenuExtractionProvider,
    PageInput,
    ProviderError,
)
from app.domains.menu.extract.schema import Defaults, PageExtraction
from app.domains.menu.models import MenuImport
from app.domains.tenant.models import TaxClass
from app.storage import ObjectStorage

logger = structlog.get_logger()

STALE_AFTER = timedelta(minutes=5)
_BACKOFF_SECONDS = (2.0, 6.0, 15.0)

Sleep = Callable[[float], Awaitable[None]]
_sleep: Sleep = asyncio.sleep


def set_sleep(sleep: Sleep | None) -> None:
    global _sleep
    _sleep = sleep or asyncio.sleep


def _fail_message(pages_failed: list[int]) -> str:
    listed = ", ".join(str(n) for n in pages_failed[:10])
    return f"Some pages could not be read (page {listed}). Try again to retry only those."


async def _claim(restaurant_id: UUID, import_id: UUID) -> MenuImport | None:
    now = clock.utcnow()
    async with tenant_session(restaurant_id) as session:
        claimed = await session.execute(
            update(MenuImport)
            .where(
                MenuImport.id == import_id,
                (MenuImport.status == "queued")
                | (
                    (MenuImport.status == "processing")
                    & (MenuImport.updated_at < now - STALE_AFTER)
                ),
            )
            .values(status="processing", stage="Reading your files", error=None, updated_at=now)
            .returning(MenuImport.id)
        )
        if claimed.scalar_one_or_none() is None:
            return None
        return await session.get(MenuImport, import_id)


async def _save(restaurant_id: UUID, import_id: UUID, **values: Any) -> None:
    async with tenant_session(restaurant_id) as session:
        await session.execute(
            update(MenuImport)
            .where(MenuImport.id == import_id)
            .values(updated_at=clock.utcnow(), **values)
        )


async def _extract_page(
    provider: MenuExtractionProvider, page: PageInput, usage: dict[str, Any], entry: dict[str, Any]
) -> PageExtraction | None:
    """Up to `menu_extraction_max_attempts` tries with exponential backoff. Returns None when the
    page could not be read; the reason is recorded on `entry` in words safe to show."""
    attempts = settings.menu_extraction_max_attempts
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            result = await provider.extract_page(page)
            usage["requests"] += result.usage.requests
            usage["prompt_tokens"] += result.usage.prompt_tokens
            usage["completion_tokens"] += result.usage.completion_tokens
            usage["llm_ms"] += int((time.monotonic() - started) * 1000)
            return PageExtraction.model_validate(result.data)
        except ValidationError:
            usage["requests"] += 1
            error, retryable, wait = "The model's answer did not match the menu format.", True, None
            logger.warning("menu_page_malformed", page=page.number, attempt=attempt)
        except ProviderError as exc:
            usage["llm_failures"] += 1
            error, retryable, wait = str(exc), exc.retryable, exc.retry_after
            logger.warning(
                "menu_page_failed", page=page.number, attempt=attempt, retryable=retryable
            )
        entry["attempts"] += 1
        entry["error"] = error
        if not retryable or attempt == attempts:
            return None
        usage["retries"] += 1
        await _sleep(wait or _BACKOFF_SECONDS[min(attempt - 1, len(_BACKOFF_SECONDS) - 1)])
    return None  # pragma: no cover - the loop always returns


def _fresh_usage(previous: dict[str, Any]) -> dict[str, Any]:
    keys = ("requests", "prompt_tokens", "completion_tokens", "llm_ms", "llm_failures", "retries")
    return {k: int(previous.get(k, 0)) for k in keys}


def _cost_usd(usage: dict[str, Any]) -> float:
    cost: float = round(
        usage["prompt_tokens"] * settings.menu_extraction_input_usd_per_mtok / 1_000_000
        + usage["completion_tokens"] * settings.menu_extraction_output_usd_per_mtok / 1_000_000,
        4,
    )
    return cost


async def run_extraction(
    restaurant_id: UUID,
    outlet_id: UUID,
    import_id: UUID,
    provider: MenuExtractionProvider,
    storage: ObjectStorage,
) -> str:
    """Returns the job's final status, or "skipped" if another worker owns it. Never raises for a
    claimed job: an unexpected error ends it as `failed` so the owner can try again."""
    try:
        return await _run(restaurant_id, outlet_id, import_id, provider, storage)
    except Exception:
        logger.exception("menu_extraction_failed", reason="unexpected", import_id=str(import_id))
        await _save(
            restaurant_id,
            import_id,
            status="failed",
            stage=None,
            error="Something went wrong while reading the menu. Try again.",
        )
        return "failed"


async def _run(
    restaurant_id: UUID,
    outlet_id: UUID,
    import_id: UUID,
    provider: MenuExtractionProvider,
    storage: ObjectStorage,
) -> str:
    log = logger.bind(
        restaurant_id=str(restaurant_id), outlet_id=str(outlet_id), import_id=str(import_id)
    )
    job = await _claim(restaurant_id, import_id)
    if job is None:
        return "skipped"
    started = time.monotonic()
    usage = _fresh_usage(job.usage)
    try:
        blobs = [(f["name"], await storage.get(f["key"])) for f in job.files]
        pages = await asyncio.to_thread(load_pages, blobs)
    except FileProblem as exc:
        await _save(restaurant_id, import_id, status="failed", stage=None, error=str(exc))
        log.warning("menu_extraction_failed", reason="unreadable_files")
        return "failed"
    except Exception:
        await _save(
            restaurant_id,
            import_id,
            status="failed",
            stage=None,
            error="The uploaded files could not be loaded. Try again, or upload them again.",
        )
        log.exception("menu_extraction_failed", reason="storage")
        return "failed"

    if len(pages) > settings.menu_extraction_max_pages:
        await _save(
            restaurant_id,
            import_id,
            status="failed",
            stage=None,
            error=f"This menu has {len(pages)} pages; "
            f"the limit is {settings.menu_extraction_max_pages}.",
        )
        log.warning("menu_extraction_failed", reason="too_many_pages", pages=len(pages))
        return "failed"

    entries: list[dict[str, Any]] = job.pages or [
        {
            "n": p.number,
            "label": p.label,
            "mode": "text" if p.text is not None else "image",
            "status": "pending",
            "attempts": 0,
            "error": None,
            "result": None,
        }
        for p in pages
    ]
    log.info("menu_extraction_started", pages=len(pages))
    for page, entry in zip(pages, entries, strict=True):
        if entry["status"] == "done":
            continue
        await _save(
            restaurant_id,
            import_id,
            stage=f"Reading page {page.number} of {len(pages)}",
            pages=entries,
            usage=usage,
        )
        entry["error"] = None
        result = await _extract_page(provider, page, usage, entry)
        if result is None:
            entry["status"] = "failed"
        else:
            entry["status"], entry["result"] = "done", result.model_dump()
            log.info("menu_page_processed", page=page.number, mode=entry["mode"])
        await _save(restaurant_id, import_id, pages=entries, usage=usage)

    failed = [e["n"] for e in entries if e["status"] != "done"]
    usage["pages"] = len(entries)
    usage["failed_pages"] = len(failed)
    usage["estimated_cost_usd"] = _cost_usd(usage)
    usage["duration_ms"] = int((time.monotonic() - started) * 1000)
    if failed:
        await _save(
            restaurant_id,
            import_id,
            status="failed",
            stage=None,
            error=_fail_message(failed),
            pages=entries,
            usage=usage,
        )
        log.warning(
            "menu_extraction_failed", reason="pages", failed_page_numbers=failed, **_metrics(usage)
        )
        return "failed"

    await _save(restaurant_id, import_id, stage="Checking the menu", pages=entries, usage=usage)
    rows = rows_from_pages((e["n"], PageExtraction.model_validate(e["result"])) for e in entries)
    if not rows:
        await _save(
            restaurant_id,
            import_id,
            status="failed",
            stage=None,
            usage=usage,
            error="We could not find a menu in these files. "
            "Try a clearer photo or a different file.",
        )
        log.warning("menu_extraction_failed", reason="no_menu", **_metrics(usage))
        return "failed"

    async with tenant_session(restaurant_id) as session:
        defaults = await _default_tax_classes(session, outlet_id)
        await session.execute(
            update(MenuImport)
            .where(MenuImport.id == import_id)
            .values(
                status="ready",
                stage=None,
                error=None,
                updated_at=clock.utcnow(),
                rows=[r.model_dump() for r in rows],
                defaults=defaults.model_dump(),
                pages=entries,
                usage=usage,
            )
        )
    for f in job.files:  # the menu is now text; the originals are no longer needed
        try:
            await storage.delete(f["key"])
        except Exception:
            log.warning("menu_upload_cleanup_failed")
    await _save(restaurant_id, import_id, files=[])
    log.info(
        "menu_extraction_completed",
        items=len(rows),
        warnings=sum(bool(r.notes) for r in rows),
        **_metrics(usage),
    )
    return "ready"


def _metrics(usage: dict[str, Any]) -> dict[str, Any]:
    return {
        k: usage.get(k)
        for k in (
            "pages",
            "requests",
            "prompt_tokens",
            "completion_tokens",
            "llm_ms",
            "llm_failures",
            "retries",
            "failed_pages",
            "estimated_cost_usd",
            "duration_ms",
        )
    }


async def _default_tax_classes(session: Any, outlet_id: UUID) -> Defaults:
    """Pre-select a tax class only when there is exactly one obvious choice."""
    classes = list(await session.scalars(select(TaxClass).where(TaxClass.outlet_id == outlet_id)))
    food = [c.name for c in classes if not c.liquor_vat]
    liquor = [c.name for c in classes if c.liquor_vat]
    return Defaults(
        food_tax_class=food[0] if len(food) == 1 else None,
        liquor_tax_class=liquor[0] if len(liquor) == 1 else None,
    )
