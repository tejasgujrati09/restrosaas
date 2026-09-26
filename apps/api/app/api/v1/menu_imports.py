"""Import a menu from a PDF or photos (docs/DECISIONS.md "Menu import from PDF or photos").

Upload -> job -> background extraction -> owner reviews and edits the draft rows -> confirm.
A draft becomes the same CSV text the CSV import takes and goes through the same validator, diff
and apply as `menu/import/preview|apply`, so there is one set of menu rules. The model's output
never reaches the database directly."""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import uuid
from datetime import timedelta
from pathlib import PurePath
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, File, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from app import clock
from app.api.v1.common import ERRORS, Ctx, IdempotencyKeyHeader, idempotent_write, not_found
from app.api.v1.menu import load_menu
from app.api.v1.menu_import import (
    ImportApplyOut,
    ImportPreviewOut,
    _analyse,
    _apply,
    _preview,
)
from app.audit import audit
from app.config import settings
from app.core.permissions import Capability, assert_can
from app.core.realtime import SIGNAL_MENU_CHANGED
from app.deps import OutletContext
from app.domains.menu.extract import factory, jobs
from app.domains.menu.extract.files import MIME, FileProblem, inspect
from app.domains.menu.extract.normalize import build_csv
from app.domains.menu.extract.schema import Defaults, DraftRow
from app.domains.menu.models import MenuImport
from app.errors import ApiError
from app.realtime.hooks import after_commit, signal
from app.storage import get_storage

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/outlets/{outlet_id}/menu/imports", tags=["menu-imports"])

_SIMILARITY = 0.88
_EXPIRE_AFTER_HOURS = 24


class UsageOut(BaseModel):
    pages: int = 0
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retries: int = 0
    failed_pages: int = 0
    estimated_cost_usd: float = 0.0
    duration_ms: int = 0


class ImportJobOut(BaseModel):
    id: uuid.UUID
    status: str
    stage: str | None
    pages_total: int
    pages_done: int
    failed_pages: list[int]
    error: str | None
    usage: UsageOut | None
    created_at: str


class ReviewRowOut(DraftRow):
    errors: list[str] = []
    similar_to: str | None = None


class TaxClassOptionOut(BaseModel):
    name: str
    liquor: bool


class ImportReviewOut(BaseModel):
    job: ImportJobOut
    rows: list[ReviewRowOut]
    defaults: Defaults
    tax_classes: list[TaxClassOptionOut]
    # Problems that belong to no single row (a missing tax class default, for example).
    general_errors: list[str]
    diff: ImportPreviewOut | None
    # Rows that match an item already on the menu: confirming updates those items.
    matches_existing: int
    similar_existing: int


class ImportUpdateIn(BaseModel):
    rows: list[DraftRow]
    defaults: Defaults


def _job_out(job: MenuImport) -> ImportJobOut:
    pages = job.pages or []
    usage = UsageOut.model_validate(job.usage) if job.usage else None
    return ImportJobOut(
        id=job.id,
        status=job.status,
        stage=job.stage,
        pages_total=len(pages) or sum(int(f.get("pages", 1)) for f in job.files),
        pages_done=sum(1 for p in pages if p["status"] == "done"),
        failed_pages=[p["n"] for p in pages if p["status"] == "failed"],
        error=job.error,
        usage=usage,
        created_at=job.created_at.isoformat(),
    )


async def _load(ctx: OutletContext, import_id: uuid.UUID, *, lock: bool = False) -> MenuImport:
    stmt = select(MenuImport).where(
        MenuImport.id == import_id, MenuImport.outlet_id == ctx.outlet_id
    )
    job = await ctx.session.scalar(stmt.with_for_update() if lock else stmt)
    if job is None:
        raise not_found("Import")
    return job


def _require_status(job: MenuImport, *allowed: str) -> None:
    if job.status not in allowed:
        raise ApiError(
            409,
            "import_wrong_state",
            f"This import is {job.status}.",
            {"status": job.status},
        )


def _draft_rows(job: MenuImport) -> list[DraftRow]:
    return [DraftRow.model_validate(r) for r in job.rows]


async def _review(ctx: OutletContext, job: MenuImport) -> ImportReviewOut:
    rows, defaults = _draft_rows(job), Defaults.model_validate(job.defaults)
    csv_text, included = build_csv(rows, defaults)
    _, diff, errors = await _analyse(ctx, csv_text)

    by_row: dict[int, list[str]] = {}
    general: list[str] = []
    for e in errors:
        if e.row >= 2 and e.row - 2 < len(included):
            by_row.setdefault(included[e.row - 2], []).append(e.message)
        else:
            general.append(e.message)

    menu = await load_menu(ctx)
    existing = {c.name.lower(): [i.name for i in c.items] for c in menu.categories}
    similar: dict[int, str] = {}
    if diff is not None:
        added = {(r.category.lower(), r.item.lower()) for r in diff.added}
        for index in included:
            row = rows[index]
            if (row.category.lower(), row.item.lower()) not in added:
                continue
            names = existing.get(row.category.lower(), [])
            close = difflib.get_close_matches(row.item, names, n=1, cutoff=_SIMILARITY)
            if close:
                similar[index] = close[0]

    tax_options = [TaxClassOptionOut(name=t.name, liquor=t.liquor_vat) for t in menu.tax_classes]
    review_rows = [
        ReviewRowOut(**r.model_dump(), errors=by_row.get(i, []), similar_to=similar.get(i))
        for i, r in enumerate(rows)
    ]
    return ImportReviewOut(
        job=_job_out(job),
        rows=review_rows,
        defaults=defaults,
        tax_classes=tax_options,
        general_errors=general,
        diff=_preview(diff, errors) if diff is not None else None,
        matches_existing=(len(diff.changed) + diff.unchanged) if diff is not None else 0,
        similar_existing=len(similar),
    )


# ------------------------------------------------------------------------------ endpoints


@router.post("", status_code=202, responses=ERRORS)
async def upload(
    ctx: Ctx,
    key: IdempotencyKeyHeader,
    files: Annotated[list[UploadFile], File(description="A PDF, or JPG/PNG pages in order.")],
) -> ImportJobOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)
    if not factory.configured():
        raise ApiError(
            503,
            "menu_extraction_not_configured",
            "Reading menus from files is not set up on this server.",
        )
    if not files:
        raise ApiError(422, "no_files", "Choose a PDF or some menu photos first.")
    if len(files) > settings.menu_extraction_max_files:
        raise ApiError(
            422,
            "too_many_files",
            f"Upload at most {settings.menu_extraction_max_files} files at a time.",
        )

    limit = settings.menu_extraction_max_file_bytes
    uploads: list[dict[str, Any]] = []
    blobs: list[bytes] = []
    total_pages = 0
    for upload_file in files:
        name = PurePath(upload_file.filename or "menu").name[:100] or "menu"
        data = await upload_file.read(limit + 1)
        if len(data) > limit:
            raise ApiError(
                413, "file_too_large", f"{name} is too large (limit {limit // 1_000_000} MB)."
            )
        if not data:
            raise ApiError(422, "empty_file", f"{name} is empty.")
        try:
            info = await asyncio.to_thread(inspect, name, data)
        except FileProblem as exc:
            raise ApiError(422, "unsupported_file", str(exc), {"file": name}) from exc
        total_pages += info.pages
        uploads.append({"name": name, "kind": info.kind, "pages": info.pages, "size": len(data)})
        blobs.append(data)
    if total_pages > settings.menu_extraction_max_pages:
        raise ApiError(
            422,
            "too_many_pages",
            f"These files have {total_pages} pages; "
            f"the limit is {settings.menu_extraction_max_pages}.",
        )

    async def produce() -> ImportJobOut:
        storage = get_storage()
        import_id = uuid.uuid4()
        stored: list[dict[str, Any]] = []
        try:
            for i, (meta, data) in enumerate(zip(uploads, blobs, strict=True)):
                object_key = f"menu-imports/{ctx.restaurant_id}/{import_id}/{i:03d}"
                await storage.put(object_key, data, MIME[meta["kind"]])
                stored.append({**meta, "key": object_key})
        except Exception as exc:
            for f in stored:
                await storage.delete(f["key"])
            logger.exception("menu_upload_failed", import_id=str(import_id))
            raise ApiError(
                503, "storage_unavailable", "Could not save the upload. Try again in a moment."
            ) from exc

        await _expire_old(ctx)
        now = clock.utcnow()
        job = MenuImport(
            id=import_id,
            restaurant_id=ctx.restaurant_id,
            outlet_id=ctx.outlet_id,
            created_by=ctx.actor.user_id,
            status="queued",
            stage="Waiting to start",
            files=stored,
            pages=[],
            rows=[],
            defaults={},
            usage={},
            created_at=now,
            updated_at=now,
        )
        ctx.session.add(job)
        await ctx.session.flush()
        _queue(ctx, job)
        logger.info(
            "menu_import_started",
            restaurant_id=str(ctx.restaurant_id),
            outlet_id=str(ctx.outlet_id),
            import_id=str(import_id),
            files=len(stored),
            pages=total_pages,
        )
        return _job_out(job)

    fingerprint = [hashlib.sha256(b).hexdigest() for b in blobs]
    return await idempotent_write(
        ctx, key, "POST menu/imports", {"files": fingerprint}, ImportJobOut, produce
    )


def _queue(ctx: OutletContext, job: MenuImport) -> None:
    restaurant_id, outlet_id, import_id = job.restaurant_id, job.outlet_id, job.id

    async def go() -> None:
        jobs.enqueue(restaurant_id, outlet_id, import_id)

    after_commit(ctx.session, go)


async def _expire_old(ctx: OutletContext) -> None:
    """Uploads of failed jobs are kept so the owner can retry; not forever."""
    cutoff = clock.utcnow() - timedelta(hours=_EXPIRE_AFTER_HOURS)
    old = await ctx.session.scalars(
        select(MenuImport).where(
            MenuImport.outlet_id == ctx.outlet_id,
            MenuImport.status.in_(("failed", "queued", "processing")),
            MenuImport.updated_at < cutoff,
            MenuImport.files != [],
        )
    )
    for job in old:
        for f in job.files:
            try:
                await get_storage().delete(f["key"])
            except Exception:
                logger.warning("menu_upload_cleanup_failed", import_id=str(job.id))
        job.files = []
        if job.status != "failed":
            job.status, job.error = "failed", "This import expired. Upload the menu again."


@router.get("/{import_id}", responses=ERRORS)
async def get_import(ctx: Ctx, import_id: uuid.UUID) -> ImportJobOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)
    return _job_out(await _load(ctx, import_id))


@router.get("/{import_id}/preview", responses=ERRORS)
async def preview(ctx: Ctx, import_id: uuid.UUID) -> ImportReviewOut:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)
    job = await _load(ctx, import_id)
    _require_status(job, "ready")
    return await _review(ctx, job)


@router.put("/{import_id}", responses=ERRORS)
async def update(ctx: Ctx, import_id: uuid.UUID, body: ImportUpdateIn) -> ImportReviewOut:
    """Replace the draft rows and default tax classes with the owner's corrections."""
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)
    job = await _load(ctx, import_id, lock=True)
    _require_status(job, "ready")
    if len(body.rows) > 2000:
        raise ApiError(422, "too_many_rows", "A menu import can have at most 2,000 rows.")
    corrected = sum(1 for old, new in zip(_draft_rows(job), body.rows, strict=False) if old != new)
    job.rows = [r.model_dump() for r in body.rows]
    job.defaults = body.defaults.model_dump()
    job.updated_at = clock.utcnow()
    await ctx.session.flush()
    logger.info("menu_import_edited", import_id=str(job.id), corrected_rows=corrected)
    return await _review(ctx, job)


@router.get("/{import_id}/csv", responses=ERRORS)
async def download_csv(ctx: Ctx, import_id: uuid.UUID) -> Response:
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)
    job = await _load(ctx, import_id)
    _require_status(job, "ready", "applied")
    text, _ = build_csv(_draft_rows(job), Defaults.model_validate(job.defaults))
    return Response(
        text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="menu-import.csv"'},
    )


@router.post("/{import_id}/retry", status_code=202, responses=ERRORS)
async def retry(ctx: Ctx, import_id: uuid.UUID) -> ImportJobOut:
    """Re-run a failed job. Pages that already succeeded are not sent to the model again."""
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)
    job = await _load(ctx, import_id, lock=True)
    _require_status(job, "failed", "queued")
    if not job.files:
        raise ApiError(
            409,
            "files_expired",
            "The uploaded files are gone. Upload the menu again.",
            {"status": job.status},
        )
    job.status, job.stage, job.error = "queued", "Waiting to start", None
    job.updated_at = clock.utcnow()
    await ctx.session.flush()
    _queue(ctx, job)
    return _job_out(job)


@router.post("/{import_id}/confirm", responses=ERRORS)
async def confirm(
    ctx: Ctx,
    import_id: uuid.UUID,
    key: IdempotencyKeyHeader,
    diff_hash: Annotated[str, Query(min_length=64, max_length=64)],
) -> ImportApplyOut:
    """Apply the reviewed draft with the existing CSV import. All or nothing: one transaction."""
    assert_can(ctx.actor, Capability.EDIT_MENU_FULL, ctx.outlet_id)

    async def produce() -> ImportApplyOut:
        job = await _load(ctx, import_id, lock=True)
        _require_status(job, "ready")
        text, _ = build_csv(_draft_rows(job), Defaults.model_validate(job.defaults))
        _, diff, errors = await _analyse(ctx, text)
        if diff is None:
            logger.warning("menu_validation_failed", import_id=str(job.id), errors=len(errors))
            raise ApiError(
                409, "import_has_errors", "Fix the highlighted rows first.", {"errors": len(errors)}
            )
        if diff.digest() != diff_hash:
            raise ApiError(
                409, "menu_changed", "The menu or your edits changed. Review the preview again."
            )
        result = await _apply(ctx, diff)
        now = clock.utcnow()
        job.status, job.stage, job.applied_at, job.updated_at = "applied", None, now, now
        audit(
            ctx,
            "menu.ai_import_applied",
            "menu_import",
            job.id,
            None,
            {**result.model_dump(), "pages": len(job.pages)},
        )
        signal(ctx.session, SIGNAL_MENU_CHANGED)
        logger.info(
            "menu_import_completed",
            import_id=str(job.id),
            items_added=result.items_added,
            items_updated=result.items_updated,
        )
        return result

    return await idempotent_write(
        ctx,
        key,
        f"POST menu/imports/{import_id}/confirm",
        {"diff_hash": diff_hash},
        ImportApplyOut,
        produce,
    )
