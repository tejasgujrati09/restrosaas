"""The owner turns the phone agent on and off. Uses the in-memory fake platform: nothing here
touches a real voice service or a real phone number. Fixture data only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.v1.voice_agent import get_voice_platform
from app.config import settings
from app.core.permissions import Role
from app.main import app
from tests.api.guest_helpers import manager, staff, waiter, wipe_tabs
from tests.api.helpers import Menu
from tests.conftest import Seed
from tests.voice_fakes import FakeVoicePlatform

pytestmark = pytest.mark.usefixtures("fake_clock")

FREE = (1001, "+910000000001")
BUSY = (1002, "+910000000002")


@pytest.fixture
async def platform(
    seed: Seed, owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FakeVoicePlatform]:
    fake = FakeVoicePlatform(numbers=[FREE, BUSY])
    fake.numbers[BUSY[0]] = type(fake.numbers[BUSY[0]])(BUSY[0], BUSY[1], "someone-elses-agent")
    app.dependency_overrides[get_voice_platform] = lambda: fake
    monkeypatch.setattr(settings, "voice_tools_base_url", "https://tools.example.test")
    monkeypatch.setattr(settings, "voice_sr_number", None)
    yield fake
    app.dependency_overrides.pop(get_voice_platform, None)
    await wipe_tabs(owner_engine, seed)
    async with owner_engine.begin() as conn:
        for table in ("customer_address", "customer", "voice_agent", "idempotency_key"):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE restaurant_id = :r"), {"r": seed.restaurant_a}
            )
        await conn.execute(
            text("DELETE FROM audit_log WHERE restaurant_id = :r AND action LIKE 'voice.%'"),
            {"r": seed.restaurant_a},
        )


def _owner(seed: Seed) -> dict[str, str]:
    return staff(seed, seed.owner_a, Role.OWNER)


def _url(seed: Seed, suffix: str = "") -> str:
    return f"/v1/outlets/{seed.outlet_a}/voice-agent{suffix}"


def _key(fake: FakeVoicePlatform) -> str:
    (spec,) = fake.agents.values()
    keys = {tool.secret_headers["X-Voice-Key"] for tool in spec.tools}
    assert len(keys) == 1
    return keys.pop()


async def _tool(
    client: httpx.AsyncClient, key: str, name: str, body: dict[str, Any]
) -> httpx.Response:
    return await client.post(f"/v1/voice/tools/{name}", json=body, headers={"X-Voice-Key": key})


async def test_status_is_off_before_anything(
    client: httpx.AsyncClient, seed: Seed, platform: FakeVoicePlatform
) -> None:
    r = await client.get(_url(seed), headers=_owner(seed))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "off" and r.json()["enabled"] is False


async def test_enable_builds_the_agent_from_the_menu_and_links_a_free_number(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform
) -> None:
    r = await client.post(_url(seed, "/enable"), headers=_owner(seed))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["enabled"], body["status"], body["phone_number"]) == (True, "active", FREE[1])
    assert body["last_error"] is None
    assert platform.numbers[FREE[0]].linked_agent_id is not None
    assert FREE[0] in platform.caller_mapped

    (agent_id, spec) = next(iter(platform.agents.items()))
    assert platform.active[agent_id] is True
    assert spec.name == "Brand a phone orders"
    assert spec.call_variables == ("caller",)
    assert [t.name for t in spec.tools] == ["lookup_customer", "save_address", "place_order"]
    assert env.item["name"] in spec.system_prompt
    assert f"item_id={env.item['id']}" in spec.system_prompt
    assert "₹320.00" in spec.system_prompt  # the menu's price, formatted
    assert _key(platform) not in r.text  # the key never reaches the owner


async def test_the_stored_hash_is_not_the_key(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    platform: FakeVoicePlatform,
    owner_engine: AsyncEngine,
) -> None:
    await client.post(_url(seed, "/enable"), headers=_owner(seed))
    async with owner_engine.connect() as conn:
        stored = await conn.scalar(
            text("SELECT key_hash FROM voice_agent WHERE outlet_id = :o"), {"o": seed.outlet_a}
        )
    assert stored and stored not in _key(platform)
    assert _key(platform).split(".")[1] != stored


async def test_end_to_end_enable_then_a_phone_order_then_the_manager_accepts(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform
) -> None:
    await client.post(_url(seed, "/enable"), headers=_owner(seed))
    key = _key(platform)
    order = {
        "phone": "+919999900505",
        "fulfillment": "pickup",
        "items": [{"item_id": env.item["id"], "qty": 1}],
    }
    r = await _tool(client, key, "place_order", order)
    assert r.status_code == 200 and r.json()["result"].startswith("ORDER SENT FOR CONFIRMATION")
    pending = (
        await client.get(f"/v1/outlets/{seed.outlet_a}/staff/voice-orders", headers=manager(seed))
    ).json()
    assert len(pending) == 1
    accepted = await client.post(
        f"/v1/outlets/{seed.outlet_a}/staff/voice-orders/{pending[0]['order_id']}/accept",
        headers=manager(seed),
    )
    assert accepted.json()["status"] == "accepted"


@pytest.mark.parametrize("who", ["manager", "waiter"])
async def test_only_the_owner_can_switch_it_on_or_off(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform, who: str
) -> None:
    headers = manager(seed) if who == "manager" else waiter(seed)
    for path, method in (
        ("", "get"),
        ("/enable", "post"),
        ("/disable", "post"),
        ("/resync", "post"),
    ):
        r = await getattr(client, method)(_url(seed, path), headers=headers)
        assert r.status_code == 403, (path, r.text)
    assert platform.calls == []


async def test_enabling_twice_is_refused(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform
) -> None:
    await client.post(_url(seed, "/enable"), headers=_owner(seed))
    again = await client.post(_url(seed, "/enable"), headers=_owner(seed))
    assert again.status_code == 409 and again.json()["code"] == "voice_already_enabled"
    assert len(platform.agents) == 1


async def test_an_empty_menu_is_refused_before_anything_is_created(
    client: httpx.AsyncClient, seed: Seed, platform: FakeVoicePlatform
) -> None:
    r = await client.post(_url(seed, "/enable"), headers=_owner(seed))
    assert r.status_code == 409 and r.json()["code"] == "menu_empty"
    assert platform.calls == []


async def test_a_linked_number_is_never_taken(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    platform: FakeVoicePlatform,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "voice_sr_number", BUSY[1])
    r = await client.post(_url(seed, "/enable"), headers=_owner(seed))
    assert r.status_code == 409 and r.json()["code"] == "number_in_use"
    assert platform.agents == {}
    assert platform.numbers[BUSY[0]].linked_agent_id == "someone-elses-agent"
    assert "link_number" not in platform.calls and "create_agent" not in platform.calls
    assert (await client.get(_url(seed), headers=_owner(seed))).json()["status"] == "off"


async def test_an_unknown_number_and_no_free_number_are_refused(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    platform: FakeVoicePlatform,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "voice_sr_number", "+910000009999")
    r = await client.post(_url(seed, "/enable"), headers=_owner(seed))
    assert r.status_code == 409 and r.json()["code"] == "number_unavailable"

    monkeypatch.setattr(settings, "voice_sr_number", None)
    del platform.numbers[FREE[0]]
    r = await client.post(_url(seed, "/enable"), headers=_owner(seed))
    assert r.status_code == 409 and r.json()["code"] == "no_number_available"
    assert platform.agents == {}


@pytest.mark.parametrize("failing", ["create_agent", "pass_caller_to_agent", "link_number"])
async def test_a_platform_failure_is_recorded_and_leaves_nothing_behind(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform, failing: str
) -> None:
    platform.fail_next(failing)
    r = await client.post(_url(seed, "/enable"), headers=_owner(seed))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["enabled"], body["status"]) == (False, "failed")
    assert body["last_error"] == f"{failing} failed (HTTP 500)"
    assert platform.agents == {}  # a half-made agent is removed
    assert platform.numbers[FREE[0]].linked_agent_id is None  # and no number is left linked

    retry = await client.post(_url(seed, "/enable"), headers=_owner(seed))
    assert retry.status_code == 200 and retry.json()["status"] == "active"
    assert len(platform.agents) == 1


async def test_disable_stops_the_agent_and_cuts_off_its_tools(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform
) -> None:
    await client.post(_url(seed, "/enable"), headers=_owner(seed))
    key = _key(platform)
    (agent_id,) = platform.agents
    r = await client.post(_url(seed, "/disable"), headers=_owner(seed))
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    assert platform.active[agent_id] is False
    assert (await _tool(client, key, "lookup_customer", {})).status_code == 401
    assert (await client.post(_url(seed, "/disable"), headers=_owner(seed))).status_code == 409


async def test_enabling_again_reuses_the_agent_and_rotates_the_key(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform
) -> None:
    await client.post(_url(seed, "/enable"), headers=_owner(seed))
    old_key = _key(platform)
    (agent_id,) = platform.agents
    await client.post(_url(seed, "/disable"), headers=_owner(seed))
    r = await client.post(_url(seed, "/enable"), headers=_owner(seed))
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert list(platform.agents) == [agent_id] and platform.active[agent_id] is True
    new_key = _key(platform)
    assert new_key != old_key
    assert (await _tool(client, old_key, "lookup_customer", {})).status_code == 401
    assert (await _tool(client, new_key, "lookup_customer", {})).status_code == 200


async def test_a_disable_that_cannot_reach_the_platform_still_cuts_off_the_tools(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform
) -> None:
    await client.post(_url(seed, "/enable"), headers=_owner(seed))
    key = _key(platform)
    platform.fail_next("set_agent_active")
    r = await client.post(_url(seed, "/disable"), headers=_owner(seed))
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    assert "may still answer" in r.json()["last_error"]
    assert (await _tool(client, key, "lookup_customer", {})).status_code == 401


async def test_resync_picks_up_menu_changes_and_rotates_the_key(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform
) -> None:
    await client.post(_url(seed, "/enable"), headers=_owner(seed))
    old_key = _key(platform)
    added = await client.post(
        f"{env.base}/items",
        json={
            "category_id": env.category["id"],
            "name": "G Fresh Lime Soda",
            "base_price_paise": 9000,
            "tax_class_id": env.tax_food["id"],
        },
        headers=env.owner,
    )
    assert added.status_code in (200, 201), added.text
    (agent_id,) = platform.agents
    assert "Fresh Lime Soda" not in platform.agents[agent_id].system_prompt

    r = await client.post(_url(seed, "/resync"), headers=_owner(seed))
    assert r.status_code == 200 and r.json()["last_error"] is None
    assert "G Fresh Lime Soda" in platform.agents[agent_id].system_prompt
    assert _key(platform) != old_key
    assert (await _tool(client, old_key, "lookup_customer", {})).status_code == 401
    assert (await _tool(client, _key(platform), "lookup_customer", {})).status_code == 200


async def test_sold_out_items_are_left_out_of_the_prompt(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform
) -> None:
    await client.put(
        f"{env.base}/items/{env.item['id']}/availability",
        json={"available": False},
        headers=env.owner,
    )
    other = await client.post(
        f"{env.base}/items",
        json={
            "category_id": env.category["id"],
            "name": "G Available Item",
            "base_price_paise": 5000,
            "tax_class_id": env.tax_food["id"],
        },
        headers=env.owner,
    )
    assert other.status_code in (200, 201), other.text
    await client.post(_url(seed, "/enable"), headers=_owner(seed))
    (spec,) = platform.agents.values()
    assert "G Available Item" in spec.system_prompt
    assert env.item["name"] not in spec.system_prompt


async def test_a_failed_resync_keeps_the_old_key_working(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform
) -> None:
    await client.post(_url(seed, "/enable"), headers=_owner(seed))
    key = _key(platform)
    platform.fail_next("update_agent")
    r = await client.post(_url(seed, "/resync"), headers=_owner(seed))
    assert r.status_code == 200 and "re-sync failed" in r.json()["last_error"]
    assert r.json()["status"] == "active"
    assert (await _tool(client, key, "lookup_customer", {})).status_code == 200


async def test_resync_needs_an_active_agent(
    client: httpx.AsyncClient, seed: Seed, env: Menu, platform: FakeVoicePlatform
) -> None:
    r = await client.post(_url(seed, "/resync"), headers=_owner(seed))
    assert r.status_code == 409 and r.json()["code"] == "voice_not_active"


async def test_enable_and_disable_are_audited(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    platform: FakeVoicePlatform,
    owner_engine: AsyncEngine,
) -> None:
    await client.post(_url(seed, "/enable"), headers=_owner(seed))
    await client.post(_url(seed, "/disable"), headers=_owner(seed))
    async with owner_engine.connect() as conn:
        actions = [
            r[0]
            for r in await conn.execute(
                text(
                    "SELECT action FROM audit_log WHERE restaurant_id = :r "
                    "AND action LIKE 'voice.%' ORDER BY at"
                ),
                {"r": seed.restaurant_a},
            )
        ]
    assert actions == ["voice.enabled", "voice.disabled"]


async def test_without_server_credentials_it_says_so(
    client: httpx.AsyncClient, seed: Seed, env: Menu, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides.pop(get_voice_platform, None)
    monkeypatch.setattr(settings, "gupshup_api_key", None)
    r = await client.post(_url(seed, "/enable"), headers=_owner(seed))
    assert r.status_code == 503 and r.json()["code"] == "voice_not_configured"
