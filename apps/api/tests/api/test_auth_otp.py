from __future__ import annotations

import re

import httpx
import pytest

from app.auth import OTP_MAX_ATTEMPTS, decode_token, otp_store
from app.core.permissions import Role
from tests.conftest import Seed, bearer


async def _request_code(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str], phone: str
) -> str:
    r = await client.post("/v1/auth/otp/request", json={"phone": phone})
    assert r.status_code == 202
    match = re.search(rf"OTP for {re.escape(phone)}: (\d{{6}})", capsys.readouterr().out)
    assert match, "dev OTP was not printed to the console"
    return match.group(1)


async def test_full_login_flow_returns_working_token_with_roles(
    client: httpx.AsyncClient, seed: Seed, capsys: pytest.CaptureFixture[str]
) -> None:
    phone = seed.phones["manager_a"]
    code = await _request_code(client, capsys, phone)
    r = await client.post("/v1/auth/otp/verify", json={"phone": phone, "code": code})
    assert r.status_code == 200
    token = r.json()["access_token"]

    user_id, claims = decode_token(token)
    assert user_id == seed.manager_a
    assert [(c.restaurant_id, c.outlet_id, c.role) for c in claims] == [
        (seed.restaurant_a, seed.outlet_a, Role.MANAGER)
    ]
    ok = await client.get(f"/v1/outlets/{seed.outlet_a}/tables", headers=bearer(token))
    assert ok.status_code == 200


async def test_inactive_role_is_not_granted(
    client: httpx.AsyncClient, seed: Seed, capsys: pytest.CaptureFixture[str]
) -> None:
    phone = seed.phones["inactive_waiter_a"]
    code = await _request_code(client, capsys, phone)
    r = await client.post("/v1/auth/otp/verify", json={"phone": phone, "code": code})
    _, claims = decode_token(r.json()["access_token"])
    assert claims == []


async def test_unknown_phone_gets_202_but_no_code(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    r = await client.post("/v1/auth/otp/request", json={"phone": "+919000000000"})
    assert r.status_code == 202
    assert "OTP for" not in capsys.readouterr().out


async def test_wrong_code_is_rejected_and_code_is_single_use(
    client: httpx.AsyncClient, seed: Seed, capsys: pytest.CaptureFixture[str]
) -> None:
    phone = seed.phones["waiter_a"]
    code = await _request_code(client, capsys, phone)
    wrong = "000000" if code != "000000" else "111111"
    bad = await client.post("/v1/auth/otp/verify", json={"phone": phone, "code": wrong})
    assert (bad.status_code, bad.json()["code"]) == (401, "invalid_otp")
    good = await client.post("/v1/auth/otp/verify", json={"phone": phone, "code": code})
    assert good.status_code == 200
    replay = await client.post("/v1/auth/otp/verify", json={"phone": phone, "code": code})
    assert replay.status_code == 401


async def test_code_locks_after_too_many_wrong_attempts(
    client: httpx.AsyncClient, seed: Seed, capsys: pytest.CaptureFixture[str]
) -> None:
    phone = seed.phones["waiter_a"]
    code = await _request_code(client, capsys, phone)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(OTP_MAX_ATTEMPTS):
        await client.post("/v1/auth/otp/verify", json={"phone": phone, "code": wrong})
    r = await client.post("/v1/auth/otp/verify", json={"phone": phone, "code": code})
    assert r.status_code == 401


async def test_expired_code_is_rejected(
    client: httpx.AsyncClient,
    seed: Seed,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phone = seed.phones["waiter_a"]
    code = await _request_code(client, capsys, phone)
    monkeypatch.setattr("app.auth.time.monotonic", lambda: 10**12)
    r = await client.post("/v1/auth/otp/verify", json={"phone": phone, "code": code})
    assert r.status_code == 401


async def test_code_for_phone_without_user_is_rejected(client: httpx.AsyncClient) -> None:
    phone = "+919111111111"
    code = otp_store.issue(phone)
    r = await client.post("/v1/auth/otp/verify", json={"phone": phone, "code": code})
    assert r.status_code == 401


async def test_verify_without_request_is_rejected(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/auth/otp/verify", json={"phone": "+919222222222", "code": "123456"})
    assert r.status_code == 401


async def test_malformed_phone_is_422_with_error_shape(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/auth/otp/request", json={"phone": "12345"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert "errors" in body["details"]


async def test_non_dev_mode_does_not_print_code(
    client: httpx.AsyncClient,
    seed: Seed,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.v1.auth.settings.otp_dev_mode", False)
    r = await client.post("/v1/auth/otp/request", json={"phone": seed.phones["waiter_a"]})
    assert r.status_code == 202
    assert "OTP for" not in capsys.readouterr().out
