"""`Idempotency-Key` handling for client writes (CLAUDE.md §3).

The key row is written in the same transaction as the handler's changes, so
either both commit or neither does. A concurrent request with the same key
blocks on the primary key until the first finishes, then replays its stored
response. Only successful responses are stored; a failed attempt rolls back
and may be retried with the same key.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.deps import OutletContext
from app.domains.staff.models import IdempotencyKey
from app.errors import ApiError


def fingerprint(method: str, path: str, body: Any) -> str:
    canonical = json.dumps(jsonable_encoder(body), sort_keys=True, default=str)
    return hashlib.sha256(f"{method} {path} {canonical}".encode()).hexdigest()


async def run_idempotent[T](
    ctx: OutletContext,
    key: UUID | None,
    request_hash: str,
    response_type: Any,
    produce: Callable[[], Awaitable[T]],
) -> T:
    if key is None:
        return await produce()

    claimed = await ctx.session.execute(
        insert(IdempotencyKey)
        .values(
            restaurant_id=ctx.restaurant_id,
            user_id=ctx.actor.user_id,
            key=key,
            method="",
            path="",
            request_hash=request_hash,
        )
        .on_conflict_do_nothing()
        .returning(IdempotencyKey.key)
    )
    if claimed.scalar_one_or_none() is not None:
        result = await produce()
        row = await ctx.session.get(IdempotencyKey, (ctx.restaurant_id, ctx.actor.user_id, key))
        assert row is not None
        row.response = {"result": jsonable_encoder(result)}
        row.status_code = 200
        return result

    existing = await ctx.session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.restaurant_id == ctx.restaurant_id,
            IdempotencyKey.user_id == ctx.actor.user_id,
            IdempotencyKey.key == key,
        )
    )
    assert existing is not None
    if existing.request_hash != request_hash:
        raise ApiError(
            422,
            "idempotency_key_reused",
            "This Idempotency-Key was already used for a different request.",
        )
    if existing.response is None:
        raise ApiError(409, "request_in_progress", "This request is still being processed.")
    replayed: T = TypeAdapter(response_type).validate_python(existing.response["result"])
    return replayed
