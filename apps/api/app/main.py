from __future__ import annotations

import time
import uuid

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.v1 import (
    auth,
    invites,
    menu,
    menu_import,
    price_rules,
    settings,
    signup,
    staff,
    tables,
)
from app.config import settings as app_settings
from app.errors import install_error_handlers
from app.logging import configure_logging

configure_logging()
logger = structlog.get_logger()

app = FastAPI(title="RestoSaaS API", version="0.1.0")
install_error_handlers(app)
app.include_router(auth.router)
for module in (signup, invites, settings, menu, menu_import, price_rules, tables, staff):
    app.include_router(module.router)


class HealthOut(BaseModel):
    status: str


@app.get("/health")
async def health() -> HealthOut:
    return HealthOut(status="ok")


class RequestContextMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so contextvars bound inside route
    dependencies, such as restaurant_id, are still visible when the access
    line is logged."""

    def __init__(self, inner: ASGIApp) -> None:
        self.inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        headers = Headers(scope=scope)
        request_id = headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["x-request-id"] = request_id
            await send(message)

        try:
            await self.inner(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )


app.add_middleware(RequestContextMiddleware)
# Added last so it is outermost and answers preflight requests before anything else.
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
