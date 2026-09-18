from __future__ import annotations

import asyncio
import re
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth import decode_token
from app.core.permissions import Role
from tests.conftest import Seed, hdr, new_phone


def _code(capsys: pytest.CaptureFixture[str], phone: str) -> str:
    match = re.search(rf"OTP for {re.escape(phone)}: (\d{{6}})", capsys.readouterr().out)
    assert match
    return match.group(1)


def signup_body(phone: str, code: str, **over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "phone": phone,
        "code": code,
        "owner_name": "Asha",
        "legal_name": "TEST Legal Pvt Ltd",
        "brand_name": "TEST Cafe",
        "outlet_name": "Indiranagar",
        "state_code": "29",
    }
    body.update(over)
    return body


async def test_signup_creates_a_working_isolated_tenant(
    client: httpx.AsyncClient,
    seed: Seed,
    capsys: pytest.CaptureFixture[str],
    owner_engine: AsyncEngine,
) -> None:
    phone = new_phone()
    assert (await client.post("/v1/signup/otp", json={"phone": phone})).status_code == 202
    r = await client.post("/v1/signup", json=signup_body(phone, _code(capsys, phone)))
    assert r.status_code == 201
    out = r.json()
    _, claims = decode_token(out["access_token"])
    assert [(c.restaurant_id, c.outlet_id, c.role) for c in claims] == [
        (uuid.UUID(out["restaurant_id"]), uuid.UUID(out["outlet_id"]), Role.OWNER)
    ]

    me = hdr(out["access_token"])
    settings = await client.get(f"/v1/outlets/{out['outlet_id']}/settings", headers=me)
    body = settings.json()
    assert (body["brand_name"], body["state_code"], body["invoice_prefix"]) == (
        "TEST Cafe",
        "29",
        "INV",
    )
    assert body["ready_to_go_live"] is False  # no GSTIN or tax class yet
    # Full owner powers in their own outlet, none in anyone else's.
    assert (
        await client.post(
            f"/v1/outlets/{out['outlet_id']}/categories", json={"name": "Snacks"}, headers=me
        )
    ).status_code == 201
    assert (
        await client.get(f"/v1/outlets/{seed.outlet_a}/settings", headers=me)
    ).status_code == 403
    async with owner_engine.connect() as conn:
        audited = await conn.scalar(
            text(
                "SELECT count(*) FROM audit_log WHERE restaurant_id = :r AND action = 'restaurant.signed_up'"
            ),
            {"r": out["restaurant_id"]},
        )
    assert audited == 1


async def test_signup_code_is_single_use_and_wrong_code_is_refused(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    phone = new_phone()
    await client.post("/v1/signup/otp", json={"phone": phone})
    code = _code(capsys, phone)
    wrong = "000000" if code != "000000" else "111111"
    bad = await client.post("/v1/signup", json=signup_body(phone, wrong))
    assert (bad.status_code, bad.json()["code"]) == (401, "invalid_otp")
    assert (await client.post("/v1/signup", json=signup_body(phone, code))).status_code == 201
    replay = await client.post("/v1/signup", json=signup_body(phone, code))
    assert replay.status_code == 401  # no second restaurant from the same code


async def test_signup_login_and_signup_codes_are_separate(
    client: httpx.AsyncClient, seed: Seed, capsys: pytest.CaptureFixture[str]
) -> None:
    await client.post("/v1/auth/otp/request", json={"phone": seed.phones["owner_a"]})
    login_code = _code(capsys, seed.phones["owner_a"])
    r = await client.post("/v1/signup", json=signup_body(seed.phones["owner_a"], login_code))
    assert r.status_code == 401  # a login code cannot create a restaurant


async def test_existing_staff_can_start_a_second_restaurant(
    client: httpx.AsyncClient, seed: Seed, capsys: pytest.CaptureFixture[str]
) -> None:
    phone = seed.phones["owner_a"]
    await client.post("/v1/signup/otp", json={"phone": phone})
    r = await client.post(
        "/v1/signup", json=signup_body(phone, _code(capsys, phone), brand_name="TEST Second")
    )
    assert r.status_code == 201
    _, claims = decode_token(r.json()["access_token"])
    assert {c.restaurant_id for c in claims} == {
        seed.restaurant_a,
        uuid.UUID(r.json()["restaurant_id"]),
    }


async def test_signup_validation(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    phone = new_phone()
    await client.post("/v1/signup/otp", json={"phone": phone})
    code = _code(capsys, phone)
    assert (
        await client.post("/v1/signup", json=signup_body(phone, code, timezone="Mars/Base"))
    ).status_code == 422
    assert (
        await client.post("/v1/signup", json=signup_body(phone, code, state_code="KA"))
    ).status_code == 422
    assert (
        await client.post("/v1/signup", json=signup_body(phone, code, brand_name=""))
    ).status_code == 422
    # Rejected requests did not burn the code.
    assert (await client.post("/v1/signup", json=signup_body(phone, code))).status_code == 201


async def test_signup_otp_is_rate_limited_per_phone(client: httpx.AsyncClient) -> None:
    phone = new_phone()
    statuses = [
        (await client.post("/v1/signup/otp", json={"phone": phone})).status_code for _ in range(6)
    ]
    assert statuses == [202] * 5 + [429]
    assert (await client.post("/v1/signup/otp", json={"phone": new_phone()})).status_code == 202


async def test_signup_otp_non_dev_mode_does_not_print(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.v1.signup.settings.otp_dev_mode", False)
    assert (await client.post("/v1/signup/otp", json={"phone": new_phone()})).status_code == 202
    assert "OTP for" not in capsys.readouterr().out


async def test_login_otp_rate_limit_is_identical_for_unknown_numbers(
    client: httpx.AsyncClient,
) -> None:
    phone = "+919333333333"  # not a user
    statuses = [
        (await client.post("/v1/auth/otp/request", json={"phone": phone})).status_code
        for _ in range(6)
    ]
    assert statuses == [202] * 5 + [429]


# ------------------------------------------------------------------ idempotency


async def test_concurrent_double_submit_with_one_key_creates_exactly_one_row(
    client: httpx.AsyncClient, seed: Seed, owner_engine: AsyncEngine
) -> None:
    key = uuid.uuid4()
    owner = hdr(seed.token(seed.owner_a, Role.OWNER), key)
    url = f"/v1/outlets/{seed.outlet_a}/tables"
    responses = await asyncio.gather(
        *[client.post(url, json={"label": "IDEM1"}, headers=owner) for _ in range(6)]
    )
    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    async with owner_engine.connect() as conn:
        rows = await conn.scalar(
            text("SELECT count(*) FROM dining_table WHERE outlet_id = :o AND label = 'IDEM1'"),
            {"o": seed.outlet_a},
        )
    assert rows == 1
    await client.delete(
        f"{url}/{responses[0].json()['id']}", headers=hdr(seed.token(seed.owner_a, Role.OWNER))
    )


async def test_same_key_from_two_users_is_independent(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    key = uuid.uuid4()
    url = f"/v1/outlets/{seed.outlet_a}/tables"
    a = await client.post(
        url, json={"label": "IDEM2"}, headers=hdr(seed.token(seed.owner_a, Role.OWNER), key)
    )
    b = await client.post(
        url, json={"label": "IDEM3"}, headers=hdr(seed.token(seed.manager_a, Role.MANAGER), key)
    )
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json()["id"] != b.json()["id"]
    owner = hdr(seed.token(seed.owner_a, Role.OWNER))
    for r in (a, b):
        await client.delete(f"{url}/{r.json()['id']}", headers=owner)


async def test_failed_request_is_not_stored_so_the_key_can_be_retried(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    key = uuid.uuid4()
    url = f"/v1/outlets/{seed.outlet_a}/tables"
    owner = hdr(seed.token(seed.owner_a, Role.OWNER))
    first = (await client.post(url, json={"label": "IDEM4"}, headers=owner)).json()
    clash = await client.post(
        url, json={"label": "IDEM4"}, headers=hdr(seed.token(seed.owner_a, Role.OWNER), key)
    )
    assert clash.status_code == 409
    await client.delete(f"{url}/{first['id']}", headers=owner)
    retry = await client.post(
        url, json={"label": "IDEM4"}, headers=hdr(seed.token(seed.owner_a, Role.OWNER), key)
    )
    assert retry.status_code == 201  # the 409 was rolled back, including the key
    await client.delete(f"{url}/{retry.json()['id']}", headers=owner)


async def test_key_reuse_across_operations_is_rejected_and_bad_key_is_422(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    key = uuid.uuid4()
    url = f"/v1/outlets/{seed.outlet_a}"
    owner = hdr(seed.token(seed.owner_a, Role.OWNER), key)
    made = await client.post(f"{url}/tables", json={"label": "IDEM5"}, headers=owner)
    other = await client.post(f"{url}/stations", json={"name": "IDEM station"}, headers=owner)
    assert (other.status_code, other.json()["code"]) == (422, "idempotency_key_reused")
    bad = await client.post(
        f"{url}/tables", json={"label": "IDEM6"}, headers={**owner, "Idempotency-Key": "not-a-uuid"}
    )
    assert bad.status_code == 422
    await client.delete(
        f"{url}/tables/{made.json()['id']}", headers=hdr(seed.token(seed.owner_a, Role.OWNER))
    )


async def test_request_in_progress_marker_is_reported(
    client: httpx.AsyncClient, seed: Seed, owner_engine: AsyncEngine
) -> None:
    """A key row with no stored response (e.g. left by a crashed worker) must not
    replay garbage."""
    key = uuid.uuid4()
    from app.idempotency import fingerprint

    payload = {
        "label": "IDEM7",
        "zone": "floor",
        "seats": 2,
        "requires_waiter_confirm": False,
        "active": True,
    }
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO idempotency_key (restaurant_id, actor_id, key, method, path, request_hash) "
                "VALUES (:r, :u, :k, '', '', :h)"
            ),
            {
                "r": seed.restaurant_a,
                "u": seed.owner_a,
                "k": key,
                "h": fingerprint("POST tables", "", payload),
            },
        )
    r = await client.post(
        f"/v1/outlets/{seed.outlet_a}/tables",
        json={"label": "IDEM7"},
        headers=hdr(seed.token(seed.owner_a, Role.OWNER), key),
    )
    assert (r.status_code, r.json()["code"]) == (409, "request_in_progress")
