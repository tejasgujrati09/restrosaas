from __future__ import annotations

import json

import httpx
import pytest
from fastapi import APIRouter

from app.main import app
from tests.conftest import Seed


def _last_request_line(capsys: pytest.CaptureFixture[str]) -> dict[str, str]:
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]
    parsed = [json.loads(ln) for ln in lines]
    return [p for p in parsed if p.get("event") == "request"][-1]


async def test_health(client: httpx.AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_request_id_is_echoed_and_logged(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    r = await client.get("/health", headers={"x-request-id": "req-123"})
    assert r.headers["x-request-id"] == "req-123"
    line = _last_request_line(capsys)
    assert line["request_id"] == "req-123"


async def test_request_id_is_generated_when_absent(client: httpx.AsyncClient) -> None:
    r = await client.get("/health")
    assert len(r.headers["x-request-id"]) == 36


async def test_logs_carry_tenant_context(
    client: httpx.AsyncClient, seed: Seed, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.core.permissions import Role
    from tests.conftest import bearer

    await client.get(
        f"/v1/outlets/{seed.outlet_a}/tables",
        headers=bearer(seed.token(seed.manager_a, Role.MANAGER)),
    )
    line = _last_request_line(capsys)
    assert line["restaurant_id"] == str(seed.restaurant_a)
    assert line["outlet_id"] == str(seed.outlet_a)
    assert line["actor_user_id"] == str(seed.manager_a)
    assert "request_id" in line


async def test_unknown_route_uses_error_shape(client: httpx.AsyncClient) -> None:
    r = await client.get("/nope")
    assert r.status_code == 404
    assert set(r.json()) == {"code", "message"}


async def test_unhandled_error_is_500_without_stack_trace(client: httpx.AsyncClient) -> None:
    router = APIRouter()

    @router.get("/_boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    app.include_router(router)
    r = await client.get("/_boom")
    assert r.status_code == 500
    assert r.json() == {"code": "internal_error", "message": "Something went wrong."}
    assert "secret" not in r.text
