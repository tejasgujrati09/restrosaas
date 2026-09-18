from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header

from app.deps import GuestContext, OutletContext, get_guest_context, get_outlet_context
from app.errors import ApiError, ErrorOut
from app.idempotency import fingerprint, run_idempotent

Ctx = Annotated[OutletContext, Depends(get_outlet_context)]
GuestCtx = Annotated[GuestContext, Depends(get_guest_context)]


async def _idempotency_key(
    key: Annotated[UUID | None, Header(alias="Idempotency-Key")] = None,
) -> UUID | None:
    return key


IdempotencyKeyHeader = Annotated[UUID | None, Depends(_idempotency_key)]

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorOut},
    403: {"model": ErrorOut},
    404: {"model": ErrorOut},
    409: {"model": ErrorOut},
    422: {"model": ErrorOut},
}


def invalid(field: str, message: str, code: str = "validation_error") -> ApiError:
    return ApiError(422, code, message, {"field": field})


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found.")


async def idempotent_write[T](
    ctx: OutletContext,
    key: UUID | None,
    operation: str,
    body: Any,
    response_type: Any,
    produce: Callable[[], Awaitable[T]],
) -> T:
    """`operation` names the request (e.g. "PUT items/<id>") so a reused key
    with a different operation or body is rejected."""
    return await run_idempotent(
        ctx.session,
        ctx.restaurant_id,
        ctx.actor.user_id,
        key,
        fingerprint(operation, "", body),
        response_type,
        produce,
    )


async def guest_idempotent_write[T](
    ctx: GuestContext,
    key: UUID | None,
    operation: str,
    body: Any,
    response_type: Any,
    produce: Callable[[], Awaitable[T]],
) -> T:
    """Same as `idempotent_write`, scoped to the guest's TabSession."""
    return await run_idempotent(
        ctx.session,
        ctx.restaurant_id,
        ctx.tab_session_id,
        key,
        fingerprint(operation, "", body),
        response_type,
        produce,
    )
