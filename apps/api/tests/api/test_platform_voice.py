"""A platform admin decides whether a restaurant may use voice ordering at all, sees how its
setup went, and can retry a failed one. The backend enforces it: hiding a button proves nothing.
Fake platform and recording job queue only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.permissions import Role
from app.domains.voice.provisioning import JobOutcome
from tests.api.conftest import FREE_NUMBER, VoiceJobs
from tests.api.guest_helpers import FakeClock, staff
from tests.api.helpers import Menu
from tests.api.test_platform_admin import Admin
from tests.api.test_platform_admin import admin as admin_base  # noqa: F401  (fixture)
from tests.conftest import Seed, bearer
from tests.voice_fakes import FakeVoicePlatform

pytestmark = pytest.mark.usefixtures("fake_clock")


@pytest.fixture
async def admin(
    admin_base: Admin,  # noqa: F811
    voice_platform: FakeVoicePlatform,
    owner_engine: AsyncEngine,
) -> AsyncIterator[Admin]:
    """Voice rows and attempts point at the admin's user, so let go of it before it is deleted."""
    yield admin_base
    async with owner_engine.begin() as conn:
        params = {"u": admin_base.user_id}
        await conn.execute(
            text("UPDATE voice_agent SET enabled_by = NULL WHERE enabled_by = :u"), params
        )
        await conn.execute(
            text("UPDATE voice_agent SET disabled_by = NULL WHERE disabled_by = :u"), params
        )
        await conn.execute(
            text(
                "UPDATE voice_provisioning_attempt SET requested_by = NULL WHERE requested_by = :u"
            ),
            params,
        )


def _owner(seed: Seed) -> dict[str, str]:
    return staff(seed, seed.owner_a, Role.OWNER)


def _voice(seed: Seed, suffix: str = "") -> str:
    return f"/v1/platform/restaurants/{seed.restaurant_a}/voice{suffix}"


async def _set_allowed(
    client: httpx.AsyncClient, seed: Seed, admin: Admin, allowed: bool
) -> httpx.Response:
    return await client.put(
        f"/v1/platform/restaurants/{seed.restaurant_a}/voice-orders",
        json={"allowed": allowed},
        headers=bearer(admin.token),
    )


async def _owner_status(client: httpx.AsyncClient, seed: Seed) -> dict[str, Any]:
    r = await client.get(f"/v1/outlets/{seed.outlet_a}/voice-agent", headers=_owner(seed))
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def _owner_enable(client: httpx.AsyncClient, seed: Seed) -> httpx.Response:
    return await client.post(
        f"/v1/outlets/{seed.outlet_a}/voice-agent/enable", headers=_owner(seed)
    )


# ---- who may do it ------------------------------------------------------------------------


async def test_only_a_platform_admin_can_change_or_read_the_allowance(
    client: httpx.AsyncClient, seed: Seed, voice_platform: FakeVoicePlatform, admin: Admin
) -> None:
    calls = [
        ("put", f"/v1/platform/restaurants/{seed.restaurant_a}/voice-orders", {"allowed": True}),
        ("get", _voice(seed), None),
        ("post", _voice(seed, f"/{seed.outlet_a}/retry"), None),
    ]
    for method, url, body in calls:
        for headers in ({}, _owner(seed), staff(seed, seed.manager_a, Role.MANAGER)):
            r = await getattr(client, method)(
                url, headers=headers, **({"json": body} if body else {})
            )
            assert r.status_code in (401, 403), (method, url, r.status_code)
    still_allowed = await client.get(
        f"/v1/outlets/{seed.outlet_a}/voice-agent", headers=_owner(seed)
    )
    assert still_allowed.json()["allowed"] is True  # untouched by all of the above


async def test_the_owner_cannot_bypass_an_admin_who_has_not_allowed_it(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    admin: Admin,
) -> None:
    assert (await _set_allowed(client, seed, admin, False)).status_code == 200
    r = await _owner_enable(client, seed)
    assert r.status_code == 403 and r.json()["code"] == "voice_not_allowed"
    assert jobs.queue == [] and voice_platform.calls == []
    assert (await _owner_status(client, seed))["phase"] == "unavailable"


# ---- allowing and stopping ----------------------------------------------------------------


async def test_admin_allows_then_the_owner_sees_the_switch(
    client: httpx.AsyncClient,
    seed: Seed,
    voice_platform: FakeVoicePlatform,
    admin: Admin,
    owner_engine: AsyncEngine,
) -> None:
    await _set_allowed(client, seed, admin, False)
    assert (await _owner_status(client, seed))["phase"] == "unavailable"
    r = await _set_allowed(client, seed, admin, True)
    assert r.status_code == 200 and r.json()["allowed"] is True
    assert (await _owner_status(client, seed))["phase"] == "off"

    listed = await client.get("/v1/platform/restaurants", headers=bearer(admin.token))
    row = next(x for x in listed.json() if x["id"] == str(seed.restaurant_a))
    assert row["voice_orders_allowed"] is True
    other = next(x for x in listed.json() if x["id"] == str(seed.restaurant_b))
    assert other["voice_orders_allowed"] is False  # one restaurant's setting never leaks to another

    async with owner_engine.connect() as conn:
        audit = (
            await conn.execute(
                text(
                    "SELECT action, actor_user_id FROM audit_log WHERE restaurant_id = :r "
                    "AND action LIKE 'restaurant.voice_%' ORDER BY at"
                ),
                {"r": seed.restaurant_a},
            )
        ).all()
    assert [a[0] for a in audit] == ["restaurant.voice_disallowed", "restaurant.voice_allowed"]
    assert all(a[1] == admin.user_id for a in audit)


async def test_repeating_the_same_setting_writes_no_second_audit_row(
    client: httpx.AsyncClient,
    seed: Seed,
    voice_platform: FakeVoicePlatform,
    admin: Admin,
    owner_engine: AsyncEngine,
) -> None:
    await _set_allowed(client, seed, admin, True)  # already allowed by the fixture
    await _set_allowed(client, seed, admin, True)
    async with owner_engine.connect() as conn:
        count = await conn.scalar(
            text(
                "SELECT count(*) FROM audit_log WHERE restaurant_id = :r "
                "AND action LIKE 'restaurant.voice_%'"
            ),
            {"r": seed.restaurant_a},
        )
    assert count == 0


async def test_stopping_it_turns_off_a_running_agent_but_keeps_everything(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    admin: Admin,
) -> None:
    await _owner_enable(client, seed)
    await jobs.run_all()
    (agent_id,) = voice_platform.agents
    assert (await _owner_status(client, seed))["phase"] == "active"

    r = await _set_allowed(client, seed, admin, False)
    assert r.status_code == 200 and r.json()["outlets"][0]["phase"] == "turning_off"
    assert await jobs.run_all() == [JobOutcome.DONE]
    assert voice_platform.active[agent_id] is False  # no new calls
    assert voice_platform.numbers[FREE_NUMBER[0]].linked_agent_id == agent_id  # kept
    assert "delete_agent" not in voice_platform.calls
    body = await _owner_status(client, seed)
    assert (body["phase"], body["can_enable"]) == ("unavailable", False)

    again = await _set_allowed(client, seed, admin, False)  # a repeat queues nothing more
    assert again.status_code == 200 and jobs.queue == []

    # Allowed again: the owner can switch it back on and the same agent and number return.
    await _set_allowed(client, seed, admin, True)
    assert (await _owner_enable(client, seed)).status_code == 202
    assert await jobs.run_all() == [JobOutcome.DONE]
    assert list(voice_platform.agents) == [agent_id]


async def test_stopping_it_during_setup_cancels_the_setup(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    admin: Admin,
) -> None:
    await _owner_enable(client, seed)
    await _set_allowed(client, seed, admin, False)
    assert await jobs.run_all() == [JobOutcome.SKIPPED, JobOutcome.DONE]
    assert voice_platform.agents == {}


async def test_an_unknown_restaurant_is_a_404(
    client: httpx.AsyncClient, admin: Admin, voice_platform: FakeVoicePlatform
) -> None:
    missing = "00000000-0000-4000-8000-000000000000"
    for method, url in (
        ("put", f"/v1/platform/restaurants/{missing}/voice-orders"),
        ("get", f"/v1/platform/restaurants/{missing}/voice"),
    ):
        r = await getattr(client, method)(
            url,
            headers=bearer(admin.token),
            **({"json": {"allowed": True}} if method == "put" else {}),
        )
        assert r.status_code == 404


# ---- what the admin sees and can retry ----------------------------------------------------


async def test_admin_sees_the_failure_detail_the_owner_never_does_and_can_retry(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    admin: Admin,
    fake_clock: FakeClock,
) -> None:
    voice_platform.fail_next("update_agent")
    await _owner_enable(client, seed)
    assert await jobs.run_all() == [JobOutcome.FAILED]

    owner = await _owner_status(client, seed)
    assert "update_agent" not in str(owner) and "HTTP" not in str(owner)

    r = await client.get(_voice(seed), headers=bearer(admin.token))
    assert r.status_code == 200, r.text
    (outlet,) = r.json()["outlets"]
    assert outlet["phase"] == "failed" and outlet["can_retry"] is True
    assert "update_agent failed (HTTP 500)" in outlet["detail"]
    assert outlet["agent_id"] and outlet["phone_number"] == FREE_NUMBER[1]
    assert [s["state"] for s in outlet["steps"] if s["key"] == "configure"] == ["failed"]
    assert outlet["attempts"][0]["outcome"] == "failed"
    assert outlet["attempts"][0]["failed_step"] == "configure"

    fake_clock.advance(60)  # the retry is a later request than the first attempt
    retry = await client.post(_voice(seed, f"/{seed.outlet_a}/retry"), headers=bearer(admin.token))
    assert retry.status_code == 202, retry.text
    assert await jobs.run_all() == [JobOutcome.DONE]
    after = (await client.get(_voice(seed), headers=bearer(admin.token))).json()["outlets"][0]
    assert after["phase"] == "active" and after["can_retry"] is False
    assert [a["outcome"] for a in after["attempts"]] == ["succeeded", "failed"]
    assert after["attempts"][0]["requested_by_platform_admin"] is True


async def test_retry_only_applies_to_a_failed_setup(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    admin: Admin,
) -> None:
    await _owner_enable(client, seed)
    await jobs.run_all()
    r = await client.post(_voice(seed, f"/{seed.outlet_a}/retry"), headers=bearer(admin.token))
    assert r.status_code == 409 and r.json()["code"] == "voice_not_failed"
    nothing = await client.post(
        _voice(seed, f"/{seed.outlet_b}/retry"), headers=bearer(admin.token)
    )
    assert nothing.status_code == 404
