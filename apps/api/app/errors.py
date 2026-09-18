from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import OtpRateLimitedError
from app.core.permissions import PermissionDeniedError
from app.core.state import IllegalTransitionError

logger = structlog.get_logger()


class ErrorOut(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiError(Exception):
    def __init__(
        self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def _response(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    body = ErrorOut(code=code, message=message, details=details)
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(PermissionDeniedError)
    async def _permission_denied(_: Request, exc: PermissionDeniedError) -> JSONResponse:
        return _response(403, "permission_denied", "You do not have access to this.")

    @app.exception_handler(IllegalTransitionError)
    async def _illegal_transition(_: Request, exc: IllegalTransitionError) -> JSONResponse:
        return _response(
            409,
            "illegal_transition",
            f"That is not possible while the {exc.entity} is {exc.current}.",
            {"entity": exc.entity, "current": str(exc.current), "requested": str(exc.target)},
        )

    @app.exception_handler(OtpRateLimitedError)
    async def _rate_limited(_: Request, exc: OtpRateLimitedError) -> JSONResponse:
        return _response(
            429, "rate_limited", "Too many codes requested. Try again in a few minutes."
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        # Database constraints are the last line of defence; map them to stable codes.
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate == "23505":
            return _response(409, "duplicate", "That already exists.")
        if sqlstate == "23503":
            return _response(409, "in_use", "This is still used by other records.")
        if sqlstate in {"23514", "23502"}:
            return _response(422, "invalid_value", "One of the values is not allowed.")
        logger.error("unmapped_integrity_error", sqlstate=sqlstate)
        return _response(500, "internal_error", "Something went wrong.")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return _response(422, "validation_error", "Request is not valid.", {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _response(exc.status_code, f"http_{exc.status_code}", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", error_type=type(exc).__name__)
        return _response(500, "internal_error", "Something went wrong.")
