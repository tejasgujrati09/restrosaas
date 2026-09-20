from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth import InvalidTokenError, decode_platform_token, decode_token, issue_platform_token
from app.core.permissions import Role
from app.db.session import platform_session, session_factory, tenant_session
from tests.conftest import Seed, bearer, new_phone


@dataclass(frozen=True)
class Admin:
    user_id: uuid.UUID
    admin_id: uuid.UUID
    phone: str

    @property
    def token(self) -> str:
        return issue_platform_token(self.user_id, self.admin_id)


@pytest.fixture
async def admin(owner_engine: AsyncEngine) -> AsyncIterator[Admin]:
    user_id, admin_id, phone = uuid.uuid4(), uuid.uuid4(), new_phone()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO app_user (id, phone, name) VALUES (:i, :p, 'Ops')"),
            {"i": user_id, "p": phone},
        )
        await conn.execute(
            text("INSERT INTO platform_admin (id, user_id) VALUES (:a, :u)"),
            {"a": admin_id, "u": user_id},
        )
    yield Admin(user_id, admin_id, phone)
    async with owner_engine.begin() as conn:
        await conn.execute(text("DELETE FROM audit_log WHERE actor_user_id = :u"), {"u": user_id})
        await conn.execute(text("DELETE FROM platform_admin WHERE id = :a"), {"a": admin_id})
        await conn.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": user_id})


def _printed_code(capsys: pytest.CaptureFixture[str], phone: str) -> str | None:
    match = re.search(rf"platform OTP for {re.escape(phone)}: (\d{{6}})", capsys.readouterr().out)
    return match.group(1) if match else None


# ---- sign-in and token separation -------------------------------------------------------


async def test_admin_signs_in_with_otp_and_gets_a_platform_only_token(
    client: httpx.AsyncClient, admin: Admin, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        await client.post("/v1/platform/auth/otp/request", json={"phone": admin.phone})
    ).status_code == 202
    code = _printed_code(capsys, admin.phone)
    assert code is not None
    r = await client.post("/v1/platform/auth/otp/verify", json={"phone": admin.phone, "code": code})
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert decode_platform_token(token) == (admin.user_id, admin.admin_id)
    with pytest.raises(InvalidTokenError):
        decode_token(token)  # the staff decoder rejects it
    me = await client.get("/v1/platform/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["phone"] == admin.phone


async def test_a_staff_phone_gets_no_code_but_the_same_answer(
    client: httpx.AsyncClient, seed: Seed, capsys: pytest.CaptureFixture[str]
) -> None:
    phone = seed.phones["manager_a"]
    r = await client.post("/v1/platform/auth/otp/request", json={"phone": phone})
    assert r.status_code == 202  # identical to an admin's, so admins cannot be discovered
    assert _printed_code(capsys, phone) is None
    bad = await client.post("/v1/platform/auth/otp/verify", json={"phone": phone, "code": "123456"})
    assert bad.status_code == 401
    assert bad.json()["code"] == "invalid_otp"


async def test_a_staff_token_cannot_call_platform_routes(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    owner = bearer(seed.token(seed.owner_a, Role.OWNER))
    for method, path in (("GET", "/v1/platform/me"), ("GET", "/v1/platform/restaurants")):
        r = await client.request(method, path, headers=owner)
        assert r.status_code == 401
        assert r.json()["code"] == "invalid_token"
    assert (await client.get("/v1/platform/restaurants")).status_code == 401


async def test_a_platform_token_cannot_call_staff_routes(
    client: httpx.AsyncClient, seed: Seed, admin: Admin
) -> None:
    r = await client.get(f"/v1/outlets/{seed.outlet_a}/tables", headers=bearer(admin.token))
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_token"


async def test_a_deactivated_admin_is_locked_out_at_once(
    client: httpx.AsyncClient,
    admin: Admin,
    owner_engine: AsyncEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (await client.get("/v1/platform/me", headers=bearer(admin.token))).status_code == 200
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE platform_admin SET active = false WHERE id = :a"), {"a": admin.admin_id}
        )
    r = await client.get("/v1/platform/me", headers=bearer(admin.token))
    assert r.status_code == 403
    assert r.json()["code"] == "not_a_platform_admin"
    await client.post("/v1/platform/auth/otp/request", json={"phone": admin.phone})
    assert _printed_code(capsys, admin.phone) is None  # and cannot get a new code


# ---- what the policies allow ------------------------------------------------------------


async def test_only_an_active_admin_session_can_read_across_restaurants(
    seed: Seed, admin: Admin, owner_engine: AsyncEngine
) -> None:
    count = text("SELECT count(*) FROM restaurant WHERE id = ANY(:ids)")
    ids = {"ids": [seed.restaurant_a, seed.restaurant_b]}
    async with tenant_session(seed.restaurant_a) as s:  # a restaurant sees only itself
        assert await s.scalar(count, ids) == 1
    async with session_factory() as s, s.begin():  # no context at all
        assert await s.scalar(count, ids) == 0
    async with platform_session(uuid.uuid4()) as s:  # an id that is not an admin
        assert await s.scalar(count, ids) == 0
    async with platform_session(admin.admin_id) as s:
        assert await s.scalar(count, ids) == 2
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE platform_admin SET active = false WHERE id = :a"), {"a": admin.admin_id}
        )
    async with platform_session(admin.admin_id) as s:  # deactivated: nothing
        assert await s.scalar(count, ids) == 0


async def test_the_platform_policy_is_read_only(seed: Seed, admin: Admin) -> None:
    async with platform_session(admin.admin_id) as s:
        result = await s.execute(
            text("UPDATE restaurant SET status = 'suspended' WHERE id = :r"),
            {"r": seed.restaurant_b},
        )
        assert result.rowcount == 0  # RLS filters the row out of any write
        assert (
            await s.scalar(
                text("SELECT status FROM restaurant WHERE id = :r"), {"r": seed.restaurant_b}
            )
            == "active"
        )


async def test_audit_log_is_append_only_for_the_app_role(seed: Seed) -> None:
    async with tenant_session(seed.restaurant_a) as s:
        await s.execute(
            text(
                "INSERT INTO audit_log (id, restaurant_id, action, target_type) "
                "VALUES (:i, :r, 'test.append', 'test')"
            ),
            {"i": uuid.uuid4(), "r": seed.restaurant_a},
        )
    for statement in ("UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with tenant_session(seed.restaurant_a) as s:
                await s.execute(text(statement))


# ---- the API ----------------------------------------------------------------------------


async def test_admin_lists_restaurants_with_search_and_status_filter(
    client: httpx.AsyncClient, seed: Seed, admin: Admin
) -> None:
    headers = bearer(admin.token)
    everything = (await client.get("/v1/platform/restaurants", headers=headers)).json()
    by_id = {r["id"]: r for r in everything}
    assert str(seed.restaurant_a) in by_id
    assert by_id[str(seed.restaurant_b)]["brand_name"] == "Brand b"
    assert by_id[str(seed.restaurant_b)]["status"] == "active"

    found = (await client.get("/v1/platform/restaurants?q=Brand a", headers=headers)).json()
    assert [r["id"] for r in found if r["id"] in by_id and r["brand_name"] == "Brand a"]
    suspended = (
        await client.get("/v1/platform/restaurants?status=suspended", headers=headers)
    ).json()
    assert str(seed.restaurant_a) not in {r["id"] for r in suspended}
    assert (
        await client.get("/v1/platform/restaurants?status=bogus", headers=headers)
    ).status_code == 422


async def test_suspending_needs_a_reason_and_unknown_restaurants_are_404(
    client: httpx.AsyncClient, seed: Seed, admin: Admin
) -> None:
    headers = bearer(admin.token)
    url = f"/v1/platform/restaurants/{seed.restaurant_b}/status"
    for reason in (None, "", "  ", "ab"):
        r = await client.put(url, json={"status": "suspended", "reason": reason}, headers=headers)
        assert r.status_code == 422
        assert r.json()["details"]["field"] == "reason"
    ghost = await client.put(
        f"/v1/platform/restaurants/{uuid.uuid4()}/status",
        json={"status": "active"},
        headers=headers,
    )
    assert ghost.status_code == 404


async def test_suspend_blocks_staff_and_guests_audits_it_and_reactivate_restores(
    client: httpx.AsyncClient, seed: Seed, admin: Admin, owner_engine: AsyncEngine
) -> None:
    headers = bearer(admin.token)
    url = f"/v1/platform/restaurants/{seed.restaurant_b}/status"
    owner_b = bearer(seed.token(seed.owner_b, Role.OWNER, tenant="b"))
    tables = f"/v1/outlets/{seed.outlet_b}/tables"
    async with owner_engine.connect() as conn:
        qr = await conn.scalar(
            text("SELECT qr_token FROM dining_table WHERE restaurant_id = :r LIMIT 1"),
            {"r": seed.restaurant_b},
        )
    assert (await client.get(tables, headers=owner_b)).status_code == 200
    try:
        r = await client.put(
            url, json={"status": "suspended", "reason": "Unpaid invoice"}, headers=headers
        )
        assert r.status_code == 200
        assert r.json()["status"] == "suspended"

        # Staff can still look: reads work and the settings say why writes will not.
        assert (await client.get(tables, headers=owner_b)).status_code == 200
        settings = await client.get(f"/v1/outlets/{seed.outlet_b}/settings", headers=owner_b)
        assert settings.status_code == 200
        assert settings.json()["suspended"] is True
        # Every write is refused with a code the app can explain.
        blocked = await client.patch(
            f"/v1/outlets/{seed.outlet_b}/settings",
            json={"brand_name": "Sneaky"},
            headers={**owner_b, "Idempotency-Key": str(uuid.uuid4())},
        )
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "restaurant_suspended"
        scan = await client.post(f"/v1/qr/{qr}/session", json={})
        assert scan.status_code == 403  # guests are turned away too

        # Repeating it is a no-op: no second audit row.
        again = await client.put(
            url, json={"status": "suspended", "reason": "Unpaid invoice"}, headers=headers
        )
        assert again.status_code == 200
        log = (
            await client.get(
                f"/v1/platform/audit-log?restaurant_id={seed.restaurant_b}", headers=headers
            )
        ).json()
        suspends = [e for e in log if e["action"] == "restaurant.suspended"]
        assert len(suspends) == 1
        assert suspends[0]["after"] == {"status": "suspended", "reason": "Unpaid invoice"}
        assert suspends[0]["before"] == {"status": "active"}
        assert suspends[0]["actor_name"] == "Ops"
        assert suspends[0]["restaurant_name"] == "Brand b"
    finally:
        back = await client.put(url, json={"status": "active"}, headers=headers)
        assert back.status_code == 200
    assert back.json()["status"] == "active"
    settings = await client.get(f"/v1/outlets/{seed.outlet_b}/settings", headers=owner_b)
    assert settings.json()["suspended"] is False
    log = (
        await client.get(
            f"/v1/platform/audit-log?restaurant_id={seed.restaurant_b}", headers=headers
        )
    ).json()
    assert log[0]["action"] == "restaurant.reactivated"


async def test_audit_log_pages_newest_first_and_needs_an_admin(
    client: httpx.AsyncClient, seed: Seed, admin: Admin
) -> None:
    assert (
        await client.get(
            "/v1/platform/audit-log", headers=bearer(seed.token(seed.owner_a, Role.OWNER))
        )
    ).status_code == 401
    headers = bearer(admin.token)
    url = f"/v1/platform/restaurants/{seed.restaurant_b}/status"
    await client.put(url, json={"status": "suspended", "reason": "first"}, headers=headers)
    await client.put(url, json={"status": "active"}, headers=headers)
    page = (
        await client.get(
            f"/v1/platform/audit-log?restaurant_id={seed.restaurant_b}&limit=1", headers=headers
        )
    ).json()
    assert [e["action"] for e in page] == ["restaurant.reactivated"]
    older = (
        await client.get(
            "/v1/platform/audit-log",
            params={"restaurant_id": str(seed.restaurant_b), "before": page[0]["at"], "limit": 1},
            headers=headers,
        )
    ).json()
    assert [e["action"] for e in older] == ["restaurant.suspended"]


async def test_audit_log_can_be_limited_to_platform_actions(
    client: httpx.AsyncClient, seed: Seed, admin: Admin, owner_engine: AsyncEngine
) -> None:
    headers = bearer(admin.token)
    url = f"/v1/platform/restaurants/{seed.restaurant_b}/status"
    await client.put(url, json={"status": "suspended", "reason": "for the filter"}, headers=headers)
    await client.put(url, json={"status": "active"}, headers=headers)
    async with owner_engine.begin() as conn:  # ordinary tenant activity in the same restaurant
        await conn.execute(
            text(
                "INSERT INTO audit_log (id, restaurant_id, action, target_type) "
                "VALUES (:i, :r, 'outlet.settings_updated', 'outlet')"
            ),
            {"i": uuid.uuid4(), "r": seed.restaurant_b},
        )
    params = {"restaurant_id": str(seed.restaurant_b)}
    everything = (await client.get("/v1/platform/audit-log", params=params, headers=headers)).json()
    assert "outlet.settings_updated" in {e["action"] for e in everything}
    only = (
        await client.get(
            "/v1/platform/audit-log",
            params={**params, "action_prefix": "restaurant."},
            headers=headers,
        )
    ).json()
    assert {e["action"] for e in only} == {"restaurant.suspended", "restaurant.reactivated"}
    # A wildcard in the prefix is text, not a pattern.
    odd = await client.get(
        "/v1/platform/audit-log", params={**params, "action_prefix": "%"}, headers=headers
    )
    assert odd.json() == []
