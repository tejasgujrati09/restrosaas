from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import export_openapi
from app.main import RequestContextMiddleware


def test_export_openapi_writes_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "openapi.json"
    monkeypatch.setattr("sys.argv", ["export_openapi", str(target)])
    export_openapi.main()
    spec = json.loads(target.read_text())
    assert "/v1/outlets/{outlet_id}/tables" in spec["paths"]
    assert "/v1/auth/otp/verify" in spec["paths"]


def test_export_openapi_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["export_openapi"])
    export_openapi.main()
    assert (tmp_path / "openapi.json").exists()


async def test_middleware_passes_non_http_scopes_through() -> None:
    seen: list[str] = []

    async def inner(scope, receive, send):  # type: ignore[no-untyped-def]
        seen.append(scope["type"])

    await RequestContextMiddleware(inner)({"type": "lifespan"}, None, None)  # type: ignore[arg-type]
    assert seen == ["lifespan"]
