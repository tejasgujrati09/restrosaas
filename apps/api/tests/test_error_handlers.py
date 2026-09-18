from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.core.state import IllegalTransitionError, TabState
from app.errors import install_error_handlers


async def test_illegal_transition_is_a_409_with_the_current_state() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise IllegalTransitionError("tab", TabState.CLOSED, TabState.OPEN)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/boom")
    assert r.status_code == 409
    assert r.json() == {
        "code": "illegal_transition",
        "message": "That is not possible while the tab is closed.",
        "details": {"entity": "tab", "current": "closed", "requested": "open"},
    }
