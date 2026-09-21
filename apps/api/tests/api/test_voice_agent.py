"""The owner turns the phone agent on and off. Enabling is a background job: the request
returns at once and the job talks to the platform one resumable step at a time. Uses the
in-memory fake platform and a recording job queue: nothing here touches a real voice service or
a real phone number. Fixture data only."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import settings
from app.core.permissions import Role
from app.domains.voice.platform import AgentSpec
from app.domains.voice.provisioning import JobOutcome
from tests.api.conftest import BUSY_NUMBER, FREE_NUMBER, VoiceJobs
from tests.api.guest_helpers import FakeClock, manager, staff, waiter
from tests.api.helpers import Menu
from tests.conftest import Seed
from tests.voice_fakes import FakeVoicePlatform

pytestmark = pytest.mark.usefixtures("fake_clock")

FREE = FREE_NUMBER
BUSY = BUSY_NUMBER


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


async def _enable(client: httpx.AsyncClient, seed: Seed) -> httpx.Response:
    return await client.post(_url(seed, "/enable"), headers=_owner(seed))


async def _disable(client: httpx.AsyncClient, seed: Seed) -> httpx.Response:
    return await client.post(_url(seed, "/disable"), headers=_owner(seed))


async def _status(client: httpx.AsyncClient, seed: Seed) -> dict[str, Any]:
    r = await client.get(_url(seed), headers=_owner(seed))
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def _turn_on(client: httpx.AsyncClient, seed: Seed, jobs: VoiceJobs) -> dict[str, Any]:
    assert (await _enable(client, seed)).status_code == 202
    assert await jobs.run_all() == [JobOutcome.DONE]
    body = await _status(client, seed)
    assert body["phase"] == "active"
    return body


def _steps(body: dict[str, Any]) -> dict[str, str]:
    return {s["key"]: s["state"] for s in body["steps"]}


# ---- what the owner sees ------------------------------------------------------------------


async def test_status_is_off_before_anything(
    client: httpx.AsyncClient, seed: Seed, voice_platform: FakeVoicePlatform
) -> None:
    body = await _status(client, seed)
    assert (body["phase"], body["status"], body["enabled"]) == ("off", "off", False)
    assert body["allowed"] is True and body["can_enable"] is True and body["steps"] == []


async def test_when_the_admin_has_not_allowed_it_the_owner_cannot_enable(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE restaurant SET voice_orders_allowed = false WHERE id = :r"),
            {"r": seed.restaurant_a},
        )
    body = await _status(client, seed)
    assert (body["phase"], body["allowed"], body["can_enable"]) == ("unavailable", False, False)
    r = await _enable(client, seed)
    assert r.status_code == 403 and r.json()["code"] == "voice_not_allowed"
    assert jobs.queue == [] and voice_platform.calls == []


@pytest.mark.parametrize("who", ["manager", "waiter"])
async def test_only_the_owner_can_switch_it_on_or_off(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    who: str,
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
    assert voice_platform.calls == [] and jobs.queue == []


async def test_another_restaurants_owner_cannot_touch_this_outlet(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    other = {"Authorization": f"Bearer {seed.token(seed.owner_b, Role.OWNER, tenant='b')}"}
    for path, method in (("", "get"), ("/enable", "post"), ("/disable", "post")):
        r = await getattr(client, method)(_url(seed, path), headers=other)
        assert r.status_code in (403, 404), (path, r.status_code)
    assert jobs.queue == [] and voice_platform.calls == []


# ---- enabling: asynchronous and idempotent ------------------------------------------------


async def test_enable_returns_at_once_and_the_job_does_the_work(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    r = await _enable(client, seed)
    assert r.status_code == 202, r.text
    body = r.json()
    assert (body["phase"], body["enabled"]) == ("setting_up", False)
    assert voice_platform.calls == []  # nothing has been asked of the platform yet
    assert len(jobs.queue) == 1
    assert _steps(await _status(client, seed))["checking"] == "running"  # a refresh mid-setup

    assert await jobs.run_all() == [JobOutcome.DONE]
    done = await _status(client, seed)
    assert (done["phase"], done["enabled"], done["phone_number"]) == ("active", True, FREE[1])
    assert done["message"] is None and done["steps"] == []


async def test_the_agent_is_built_from_the_menu_and_only_switched_on_at_the_end(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    body = await _turn_on(client, seed, jobs)
    assert voice_platform.numbers[FREE[0]].linked_agent_id is not None
    assert FREE[0] in voice_platform.caller_mapped
    (agent_id, spec) = next(iter(voice_platform.agents.items()))
    assert voice_platform.active[agent_id] is True
    assert spec.name.startswith("Brand a phone orders [")
    assert spec.call_variables == ("caller",)
    assert [t.name for t in spec.tools] == ["lookup_customer", "save_address", "place_order"]
    assert env.item["name"] in spec.system_prompt
    assert "₹320.00" in spec.system_prompt
    assert _key(voice_platform) not in str(body)
    calls = voice_platform.calls
    assert calls.index("create_agent") < calls.index("update_agent") < calls.index("link_number")
    assert calls.index("link_number") < calls.index("pass_caller_to_agent")
    assert calls.index("set_agent_active") > calls.index("pass_caller_to_agent")  # on last
    assert calls.count("set_agent_active") == 1


async def test_the_stored_hash_is_not_the_key(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    owner_engine: AsyncEngine,
) -> None:
    await _turn_on(client, seed, jobs)
    async with owner_engine.connect() as conn:
        stored = await conn.scalar(
            text("SELECT key_hash FROM voice_agent WHERE outlet_id = :o"), {"o": seed.outlet_a}
        )
    assert stored and stored not in _key(voice_platform)
    assert _key(voice_platform).split(".")[1] != stored


async def test_clicking_enable_twice_makes_one_job_one_agent_one_number(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    first = await _enable(client, seed)
    second = await _enable(client, seed)
    assert first.status_code == second.status_code == 202
    assert len(jobs.queue) == 1
    assert await jobs.run_all() == [JobOutcome.DONE]
    third = await _enable(client, seed)  # and again once it is on
    assert third.status_code == 202 and third.json()["phase"] == "active"
    assert jobs.queue == []
    assert len(voice_platform.agents) == 1
    assert sum(1 for n in voice_platform.numbers.values() if n.linked_agent_id) == 2  # ours + BUSY


async def test_two_tabs_enabling_at_the_same_moment_make_one_job(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    results = await asyncio.gather(*[_enable(client, seed) for _ in range(4)])
    assert all(r.status_code == 202 for r in results)
    assert len(jobs.queue) == 1


async def test_a_duplicate_job_message_does_nothing(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _enable(client, seed)
    jobs.queue.append(jobs.queue[0])
    assert await jobs.run_all() == [JobOutcome.DONE, JobOutcome.SKIPPED]
    assert len(voice_platform.agents) == 1
    assert voice_platform.calls.count("create_agent") == 1


async def test_an_empty_menu_is_refused_before_anything_is_queued(
    client: httpx.AsyncClient, seed: Seed, voice_platform: FakeVoicePlatform, jobs: VoiceJobs
) -> None:
    r = await _enable(client, seed)
    assert r.status_code == 409 and r.json()["code"] == "menu_empty"
    assert voice_platform.calls == [] and jobs.queue == []


async def test_without_server_credentials_it_says_so(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "voice_tools_base_url", None)
    r = await _enable(client, seed)
    assert r.status_code == 503 and r.json()["code"] == "voice_not_configured"
    assert jobs.queue == []


# ---- failures at each step ----------------------------------------------------------------


async def _failed(client: httpx.AsyncClient, seed: Seed, jobs: VoiceJobs) -> dict[str, Any]:
    assert (await _enable(client, seed)).status_code == 202
    assert await jobs.run_all() == [JobOutcome.FAILED]
    body = await _status(client, seed)
    assert (body["phase"], body["enabled"], body["can_enable"]) == ("failed", False, True)
    return body


async def test_no_free_number_fails_setup_with_nothing_created(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    del voice_platform.numbers[FREE[0]]
    body = await _failed(client, seed, jobs)
    assert _steps(body)["number"] == "failed" and _steps(body)["checking"] == "done"
    assert "phone number" in body["message"] and "administrator" in body["message"]
    assert voice_platform.agents == {}

    voice_platform.numbers[FREE[0]] = type(voice_platform.numbers[BUSY[0]])(*FREE, None)
    assert (await _enable(client, seed)).status_code == 202
    assert await jobs.run_all() == [JobOutcome.DONE]
    assert (await _status(client, seed))["phone_number"] == FREE[1]


async def test_a_linked_number_is_never_taken(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "voice_sr_number", BUSY[1])
    body = await _failed(client, seed, jobs)
    assert "already in use" in body["message"]
    assert voice_platform.agents == {}
    assert voice_platform.numbers[BUSY[0]].linked_agent_id == "someone-elses-agent"
    assert "link_number" not in voice_platform.calls and "create_agent" not in voice_platform.calls


async def test_a_number_that_is_not_on_the_account_fails_setup(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "voice_sr_number", "+910000009999")
    body = await _failed(client, seed, jobs)
    assert "not available" in body["message"]
    assert voice_platform.agents == {}


async def test_two_restaurants_can_never_reserve_the_same_number(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    owner_engine: AsyncEngine,
) -> None:
    """Restaurant B already holds the only free number (its row is invisible to A under RLS);
    the unique index is what stops A taking it too."""
    other = uuid.uuid4()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO voice_agent (id, restaurant_id, outlet_id, status, sr_plan_id, "
                "phone_number, key_hash, created_at, updated_at) VALUES "
                "(:i, :r, :o, 'active', :p, :n, 'x', now(), now())"
            ),
            {"i": other, "r": seed.restaurant_b, "o": seed.outlet_b, "p": FREE[0], "n": FREE[1]},
        )
    try:
        body = await _failed(client, seed, jobs)
        assert "phone number" in body["message"]
        assert voice_platform.agents == {}
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(text("DELETE FROM voice_agent WHERE id = :i"), {"i": other})


async def test_agent_creation_failing_keeps_the_number_and_a_retry_does_not_take_another(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    owner_engine: AsyncEngine,
) -> None:
    voice_platform.numbers[1003] = type(voice_platform.numbers[FREE[0]])(
        1003, "+910000000003", None
    )
    voice_platform.fail_next("create_agent")
    body = await _failed(client, seed, jobs)
    assert _steps(body)["number"] == "done" and _steps(body)["agent"] == "failed"
    assert body["message"] == "We couldn't create the voice agent."
    assert "HTTP" not in str(body) and "create_agent" not in str(body)  # nothing raw
    reserved = body["phone_number"]
    assert reserved in (FREE[1], "+910000000003")

    assert (await _enable(client, seed)).status_code == 202
    assert await jobs.run_all() == [JobOutcome.DONE]
    assert (await _status(client, seed))["phone_number"] == reserved  # same number
    assert voice_platform.calls.count("create_agent") == 2  # one failed, one made
    assert len(voice_platform.agents) == 1
    async with owner_engine.connect() as conn:
        kinds = [
            r[0]
            for r in await conn.execute(
                text(
                    "SELECT outcome FROM voice_provisioning_attempt WHERE restaurant_id = :r "
                    "ORDER BY started_at, outcome"
                ),
                {"r": seed.restaurant_a},
            )
        ]
    assert sorted(kinds) == ["failed", "succeeded"]


async def test_agent_configuration_failing_is_retried_without_recreating_the_agent(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    voice_platform.fail_next("update_agent")
    body = await _failed(client, seed, jobs)
    assert _steps(body)["agent"] == "done" and _steps(body)["configure"] == "failed"
    (agent_id,) = voice_platform.agents
    assert voice_platform.active[agent_id] is False  # never on while half-built
    assert voice_platform.numbers[FREE[0]].linked_agent_id is None

    assert (await _enable(client, seed)).status_code == 202
    assert await jobs.run_all() == [JobOutcome.DONE]
    assert voice_platform.calls.count("create_agent") == 1
    assert list(voice_platform.agents) == [agent_id]


async def test_a_routing_failure_keeps_the_agent_and_the_link_and_only_redoes_routing(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    voice_platform.fail_next("pass_caller_to_agent")
    body = await _failed(client, seed, jobs)
    assert _steps(body)["line"] == "failed"
    (agent_id,) = voice_platform.agents
    assert voice_platform.numbers[FREE[0]].linked_agent_id == agent_id
    assert voice_platform.active[agent_id] is False  # linked but not switched on
    old_key = _key(voice_platform)

    assert (await _enable(client, seed)).status_code == 202
    assert await jobs.run_all() == [JobOutcome.DONE]
    assert voice_platform.calls.count("link_number") == 1
    assert voice_platform.calls.count("update_agent") == 1  # configure was not repeated
    assert _key(voice_platform) == old_key
    assert (await _tool(client, old_key, "lookup_customer", {})).status_code == 200


async def test_it_is_not_active_until_the_platform_confirms_the_agent_is_on(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    voice_platform.fail_next("set_agent_active")
    body = await _failed(client, seed, jobs)
    assert _steps(body)["verify"] == "failed" and body["enabled"] is False
    (agent_id,) = voice_platform.agents
    assert voice_platform.active[agent_id] is False
    assert (await _tool(client, _key(voice_platform), "lookup_customer", {})).status_code == 401

    assert (await _enable(client, seed)).status_code == 202
    assert await jobs.run_all() == [JobOutcome.DONE]
    assert (await _tool(client, _key(voice_platform), "lookup_customer", {})).status_code == 200


async def test_a_platform_timeout_is_retried_and_then_succeeds(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    voice_platform.fail_next("create_agent", retryable=True)
    assert (await _enable(client, seed)).status_code == 202
    assert await jobs.run_one() == JobOutcome.RETRY
    mid = await _status(client, seed)
    assert (mid["phase"], mid["message"]) == ("setting_up", None)  # still going, no error shown
    assert await jobs.run_all() == [JobOutcome.DONE]
    assert len(voice_platform.agents) == 1


async def test_retries_run_out_and_the_owner_is_told_it_failed(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    voice_platform.fail_next("create_agent", retryable=True)
    await _enable(client, seed)
    assert await jobs.run_one(final=True) == JobOutcome.FAILED
    assert (await _status(client, seed))["phase"] == "failed"


async def test_a_lost_create_response_finds_the_agent_instead_of_making_another(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    voice_platform.lose_response("create_agent")
    await _enable(client, seed)
    assert await jobs.run_one() == JobOutcome.RETRY
    assert len(voice_platform.agents) == 1  # it did get created
    assert await jobs.run_all() == [JobOutcome.DONE]
    assert len(voice_platform.agents) == 1 and voice_platform.calls.count("create_agent") == 1


async def test_a_lost_link_response_is_recognised_and_not_repeated(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    voice_platform.lose_response("link_number")
    await _enable(client, seed)
    assert await jobs.run_one() == JobOutcome.RETRY
    assert await jobs.run_all() == [JobOutcome.DONE]
    assert voice_platform.calls.count("link_number") == 1


async def test_an_agent_that_already_exists_on_the_platform_is_adopted(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    """The platform already has this outlet's agent (an earlier create whose answer was lost
    for good): it is reused and configured, never duplicated."""
    existing = await voice_platform.create_agent(
        AgentSpec(
            name=f"Brand a phone orders [{seed.outlet_a.hex[:8]}]",
            description="left over",
            system_prompt="old",
            first_message="hi",
            active=False,
        )
    )
    voice_platform.calls.clear()
    body = await _turn_on(client, seed, jobs)
    assert list(voice_platform.agents) == [existing]
    assert "create_agent" not in voice_platform.calls
    assert voice_platform.active[existing] is True
    assert "Brand a" in voice_platform.agents[existing].system_prompt  # reconfigured
    assert body["phone_number"] == FREE[1]


async def test_a_dead_worker_is_recovered_by_the_lease(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    owner_engine: AsyncEngine,
    fake_clock: FakeClock,
) -> None:
    await _enable(client, seed)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE voice_agent SET status = 'provisioning', updated_at = :t WHERE outlet_id = :o"
            ),
            {"t": fake_clock.now - timedelta(seconds=30), "o": seed.outlet_a},
        )
    assert await jobs.run_one() == JobOutcome.SKIPPED  # a live worker holds it
    jobs.queue.append(("enable", seed.restaurant_a, seed.outlet_a))
    fake_clock.advance(200)  # its worker has gone quiet
    assert await jobs.run_all() == [JobOutcome.DONE]


async def test_a_lost_queue_message_is_queued_again_by_the_status_poll(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    fake_clock: FakeClock,
) -> None:
    await _enable(client, seed)
    jobs.queue.clear()  # the broker lost it
    await _status(client, seed)
    assert jobs.queue == []  # too soon to say it was lost
    fake_clock.advance(31)
    await _status(client, seed)
    assert len(jobs.queue) == 1
    assert await jobs.run_all() == [JobOutcome.DONE]


# ---- disabling ----------------------------------------------------------------------------


async def test_disable_stops_the_agent_but_keeps_the_number_the_agent_and_history(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _turn_on(client, seed, jobs)
    (agent_id,) = voice_platform.agents
    r = await _disable(client, seed)
    assert r.status_code == 202 and r.json()["phase"] == "turning_off"
    assert await jobs.run_all() == [JobOutcome.DONE]
    body = await _status(client, seed)
    assert (body["phase"], body["can_enable"]) == ("off", True)
    assert voice_platform.active[agent_id] is False  # no new calls
    assert voice_platform.numbers[FREE[0]].linked_agent_id == agent_id  # reversible
    assert "delete_agent" not in voice_platform.calls


async def test_disabling_twice_makes_one_job(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _turn_on(client, seed, jobs)
    await _disable(client, seed)
    await _disable(client, seed)
    assert len(jobs.queue) == 1
    assert await jobs.run_all() == [JobOutcome.DONE]
    again = await _disable(client, seed)
    assert again.status_code == 202 and jobs.queue == []


async def test_disable_needs_something_to_disable(
    client: httpx.AsyncClient, seed: Seed, voice_platform: FakeVoicePlatform, jobs: VoiceJobs
) -> None:
    r = await _disable(client, seed)
    assert r.status_code == 409 and r.json()["code"] == "voice_not_active"


async def test_a_call_already_in_progress_can_finish_its_order_for_ten_minutes(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    fake_clock: FakeClock,
) -> None:
    await _turn_on(client, seed, jobs)
    key = _key(voice_platform)
    await _disable(client, seed)
    assert await jobs.run_all() == [JobOutcome.DONE]
    (agent_id,) = voice_platform.agents
    assert voice_platform.active[agent_id] is False  # a new call would not be answered

    fake_clock.advance(9 * 60)
    order = {
        "phone": "+919999900606",
        "fulfillment": "pickup",
        "items": [{"item_id": env.item["id"], "qty": 1}],
    }
    r = await _tool(client, key, "place_order", order)
    assert r.status_code == 200 and r.json()["result"].startswith("ORDER SENT FOR CONFIRMATION")
    pending = await client.get(
        f"/v1/outlets/{seed.outlet_a}/staff/voice-orders", headers=manager(seed)
    )
    assert len(pending.json()) == 1  # and the order is there for staff, though voice is off

    fake_clock.advance(2 * 60)  # past the window
    assert (await _tool(client, key, "lookup_customer", {})).status_code == 401


async def test_disabling_during_setup_hands_over_to_the_disable_job(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    owner_engine: AsyncEngine,
) -> None:
    async def owner_turns_it_off() -> None:
        assert (await _disable(client, seed)).status_code == 202

    voice_platform.hooks["create_agent"] = owner_turns_it_off
    await _enable(client, seed)
    assert await jobs.run_one() == JobOutcome.SUPERSEDED
    assert "link_number" not in voice_platform.calls  # setup stopped
    assert await jobs.run_all() == [JobOutcome.DONE]
    (agent_id,) = voice_platform.agents  # the agent it made was remembered, not orphaned
    assert voice_platform.active[agent_id] is False
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status, gupshup_agent_id FROM voice_agent WHERE outlet_id = :o"),
                {"o": seed.outlet_a},
            )
        ).one()
        outcomes = sorted(
            r[0]
            for r in await conn.execute(
                text("SELECT outcome FROM voice_provisioning_attempt WHERE restaurant_id = :r"),
                {"r": seed.restaurant_a},
            )
        )
    assert tuple(row) == ("disabled", agent_id)
    assert outcomes == ["succeeded", "superseded"]


async def test_disabling_before_the_job_starts_means_the_enable_job_does_nothing(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _enable(client, seed)
    await _disable(client, seed)
    assert await jobs.run_all() == [JobOutcome.SKIPPED, JobOutcome.DONE]
    assert voice_platform.agents == {}
    assert (await _status(client, seed))["phase"] == "off"


async def test_switching_off_while_it_is_being_switched_on_leaves_it_off(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    """Turned off during the last step: the switch-on is undone, not left running."""

    async def owner_turns_it_off() -> None:
        assert (await _disable(client, seed)).status_code == 202

    voice_platform.hooks["set_agent_active"] = owner_turns_it_off
    await _enable(client, seed)
    assert await jobs.run_one() == JobOutcome.SUPERSEDED
    (agent_id,) = voice_platform.agents
    assert voice_platform.active[agent_id] is False


async def test_a_failed_turn_off_is_reported_and_can_be_retried(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _turn_on(client, seed, jobs)
    voice_platform.fail_next("set_agent_active")
    await _disable(client, seed)
    assert await jobs.run_all() == [JobOutcome.FAILED]
    body = await _status(client, seed)
    assert body["phase"] == "failed" and "turning" in body["message"] and body["can_disable"]
    assert (await _enable(client, seed)).status_code == 409  # not until it is off

    await _disable(client, seed)
    assert await jobs.run_all() == [JobOutcome.DONE]
    assert (await _status(client, seed))["phase"] == "off"


async def test_enabling_again_reuses_the_agent_and_the_number_and_rotates_the_key(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _turn_on(client, seed, jobs)
    old_key = _key(voice_platform)
    (agent_id,) = voice_platform.agents
    await _disable(client, seed)
    await jobs.run_all()
    creates, links = (voice_platform.calls.count(c) for c in ("create_agent", "link_number"))

    body = await _turn_on(client, seed, jobs)
    assert body["phone_number"] == FREE[1]
    assert list(voice_platform.agents) == [agent_id] and voice_platform.active[agent_id] is True
    assert voice_platform.calls.count("create_agent") == creates
    assert voice_platform.calls.count("link_number") == links
    new_key = _key(voice_platform)
    assert new_key != old_key
    assert (await _tool(client, old_key, "lookup_customer", {})).status_code == 401
    assert (await _tool(client, new_key, "lookup_customer", {})).status_code == 200


# ---- resync -------------------------------------------------------------------------------


async def test_resync_picks_up_menu_changes_and_rotates_the_key(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _turn_on(client, seed, jobs)
    old_key = _key(voice_platform)
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
    (agent_id,) = voice_platform.agents
    assert "Fresh Lime Soda" not in voice_platform.agents[agent_id].system_prompt

    r = await client.post(_url(seed, "/resync"), headers=_owner(seed))
    assert r.status_code == 200 and r.json()["message"] is None
    assert "G Fresh Lime Soda" in voice_platform.agents[agent_id].system_prompt
    assert _key(voice_platform) != old_key
    assert (await _tool(client, old_key, "lookup_customer", {})).status_code == 401
    assert (await _tool(client, _key(voice_platform), "lookup_customer", {})).status_code == 200


async def test_sold_out_items_are_left_out_of_the_prompt(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
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
    await _turn_on(client, seed, jobs)
    (spec,) = voice_platform.agents.values()
    assert "G Available Item" in spec.system_prompt
    assert env.item["name"] not in spec.system_prompt


async def test_a_failed_resync_keeps_the_old_key_working(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _turn_on(client, seed, jobs)
    key = _key(voice_platform)
    voice_platform.fail_next("update_agent")
    r = await client.post(_url(seed, "/resync"), headers=_owner(seed))
    assert r.status_code == 200 and r.json()["phase"] == "active"
    assert (await _tool(client, key, "lookup_customer", {})).status_code == 200


async def test_resync_needs_an_active_agent(
    client: httpx.AsyncClient, seed: Seed, env: Menu, voice_platform: FakeVoicePlatform
) -> None:
    r = await client.post(_url(seed, "/resync"), headers=_owner(seed))
    assert r.status_code == 409 and r.json()["code"] == "voice_not_active"


# ---- audit and the end-to-end order -------------------------------------------------------


async def test_every_step_of_the_lifecycle_is_audited(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    owner_engine: AsyncEngine,
) -> None:
    await _turn_on(client, seed, jobs)
    await _disable(client, seed)
    await jobs.run_all()
    async with owner_engine.connect() as conn:
        actions = [
            r[0]
            for r in await conn.execute(
                text(
                    "SELECT action FROM audit_log WHERE restaurant_id = :r "
                    "AND action LIKE 'voice.%' ORDER BY at, action"
                ),
                {"r": seed.restaurant_a},
            )
        ]
    assert sorted(actions) == sorted(
        ["voice.enable_requested", "voice.provisioned", "voice.disable_requested", "voice.disabled"]
    )


async def test_end_to_end_enable_then_a_phone_order_then_the_manager_accepts(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _turn_on(client, seed, jobs)
    order = {
        "phone": "+919999900505",
        "fulfillment": "pickup",
        "items": [{"item_id": env.item["id"], "qty": 1}],
    }
    r = await _tool(client, _key(voice_platform), "place_order", order)
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
