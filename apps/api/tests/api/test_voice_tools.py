"""The phone agent's tools: authentication, what each tool tells the model, and that money,
customers and orders stay inside one restaurant. Fixture data only: fake phones and
obviously fake addresses."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domains.voice.auth import new_voice_key
from app.domains.voice.service import normalize_phone
from tests.api.guest_helpers import FakeClock, manager, wipe_tabs
from tests.api.helpers import Menu
from tests.conftest import Seed

pytestmark = pytest.mark.usefixtures("fake_clock")

CALLER = "+919999900101"
BASE = "/v1/voice/tools"


@pytest.fixture
async def voice(env: Menu, seed: Seed, owner_engine: AsyncEngine) -> AsyncIterator[dict[str, Any]]:
    key, key_hash = new_voice_key(seed.restaurant_a)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO voice_agent (id, restaurant_id, outlet_id, status, key_hash, "
                "created_at, updated_at) VALUES (:id, :r, :o, 'active', :h, now(), now())"
            ),
            {"id": uuid.uuid4(), "r": seed.restaurant_a, "o": seed.outlet_a, "h": key_hash},
        )
    yield {"menu": env, "key": key, "headers": {"X-Voice-Key": key}}
    await wipe_tabs(owner_engine, seed)
    async with owner_engine.begin() as conn:
        for table in ("customer_address", "customer", "voice_agent", "idempotency_key"):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE restaurant_id = :r"), {"r": seed.restaurant_a}
            )


async def call(
    client: httpx.AsyncClient, voice: dict[str, Any], tool: str, body: dict[str, Any]
) -> str:
    r = await client.post(f"{BASE}/{tool}", json=body, headers=voice["headers"])
    assert r.status_code == 200, r.text
    return str(r.json()["result"])


def order_body(voice: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "phone": CALLER,
        "fulfillment": "pickup",
        "items": [{"item_id": voice["menu"].item["id"], "qty": 2}],
        **extra,
    }


# ---- authentication -------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["lookup_customer", "save_address", "place_order"])
async def test_a_missing_key_is_refused(
    client: httpx.AsyncClient, voice: dict[str, Any], tool: str
) -> None:
    r = await client.post(f"{BASE}/{tool}", json={"phone": CALLER})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_voice_key"


async def test_wrong_malformed_and_foreign_keys_all_get_the_same_answer(
    client: httpx.AsyncClient, seed: Seed, voice: dict[str, Any]
) -> None:
    prefix = voice["key"].split(".")[0]
    foreign, _ = new_voice_key(seed.restaurant_b)  # a well-formed key for another restaurant
    for bad in ("nonsense", f"{prefix}.wrong-secret", foreign, "", f"{'0' * 32}.x"):
        r = await client.post(f"{BASE}/lookup_customer", json={}, headers={"X-Voice-Key": bad})
        assert (r.status_code, r.json()["code"]) == (401, "invalid_voice_key"), bad


async def test_a_disabled_agent_is_refused(
    client: httpx.AsyncClient, seed: Seed, voice: dict[str, Any], owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE voice_agent SET status = 'disabled' WHERE restaurant_id = :r"),
            {"r": seed.restaurant_a},
        )
    r = await client.post(f"{BASE}/lookup_customer", json={}, headers=voice["headers"])
    assert r.status_code == 401


# ---- phone normalisation ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9999900101", "+919999900101"),
        ("09999900101", "+919999900101"),
        ("919999900101", "+919999900101"),
        ("+91 99999 00101", "+919999900101"),
        ("+1 (415) 555-0100", "+14155550100"),
        ("", None),
        (None, None),
        ("12345", None),
        ("anonymous", None),
    ],
)
def test_normalize_phone(raw: str | None, expected: str | None) -> None:
    assert normalize_phone(raw) == expected


# ---- lookup and save_address -----------------------------------------------------------


async def test_lookup_of_an_unknown_caller_says_new(
    client: httpx.AsyncClient, voice: dict[str, Any]
) -> None:
    result = await call(client, voice, "lookup_customer", {"phone": CALLER})
    assert result.startswith("New customer")


async def test_lookup_without_a_usable_number_treats_the_caller_as_new(
    client: httpx.AsyncClient, voice: dict[str, Any]
) -> None:
    result = await call(client, voice, "lookup_customer", {"phone": "anonymous"})
    assert "unavailable" in result and "new customer" in result


async def test_a_saved_address_comes_back_with_its_id_and_the_first_is_preferred(
    client: httpx.AsyncClient, voice: dict[str, Any]
) -> None:
    saved = await call(
        client,
        voice,
        "save_address",
        {"phone": CALLER, "name": "Test Caller", "address": "1 Test Street"},
    )
    address_id = saved.split("address_id=")[1].rstrip(".")
    result = await call(client, voice, "lookup_customer", {"phone": CALLER})
    assert "Known customer (Test Caller)" in result
    assert f'address_id={address_id} "1 Test Street" (preferred)' in result


async def test_saving_the_same_address_twice_does_not_duplicate_it(
    client: httpx.AsyncClient, voice: dict[str, Any]
) -> None:
    first = await call(client, voice, "save_address", {"phone": CALLER, "address": "1 Test Street"})
    again = await call(
        client, voice, "save_address", {"phone": CALLER, "address": "  1  test STREET "}
    )
    assert first == again


async def test_make_preferred_moves_the_preference(
    client: httpx.AsyncClient, voice: dict[str, Any]
) -> None:
    await call(client, voice, "save_address", {"phone": CALLER, "address": "1 Test Street"})
    await call(
        client,
        voice,
        "save_address",
        {"phone": CALLER, "address": "2 Other Road", "make_preferred": True},
    )
    result = await call(client, voice, "lookup_customer", {"phone": CALLER})
    assert result.index("2 Other Road") < result.index("1 Test Street")
    assert result.count("(preferred)") == 1
    assert '"2 Other Road" (preferred)' in result


async def test_customers_are_per_restaurant(
    client: httpx.AsyncClient, seed: Seed, voice: dict[str, Any], owner_engine: AsyncEngine
) -> None:
    await call(client, voice, "save_address", {"phone": CALLER, "address": "1 Test Street"})
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO customer (id, restaurant_id, phone, name, created_at) "
                "VALUES (:i, :r, :p, 'Other Restaurant Customer', now())"
            ),
            {"i": uuid.uuid4(), "r": seed.restaurant_b, "p": "+919999900202"},
        )
    try:
        result = await call(client, voice, "lookup_customer", {"phone": "+919999900202"})
        assert result.startswith("New customer")
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM customer WHERE restaurant_id = :r"), {"r": seed.restaurant_b}
            )


# ---- place_order -----------------------------------------------------------------------


async def test_a_pickup_order_is_sent_for_confirmation_not_confirmed(
    client: httpx.AsyncClient, seed: Seed, voice: dict[str, Any], fake_clock: FakeClock
) -> None:
    result = await call(client, voice, "place_order", order_body(voice))
    assert result.startswith("ORDER SENT FOR CONFIRMATION for pickup, NOT YET CONFIRMED")
    assert "2 x G Paneer Tikka" in result
    assert "Do not say the order is confirmed" in result

    fake_clock.advance(3600)
    (order,) = (
        await client.get(f"/v1/outlets/{seed.outlet_a}/staff/voice-orders", headers=manager(seed))
    ).json()
    assert order["status"] == "placed"  # still waiting for a person, an hour later
    assert order["fulfillment_type"] == "pickup"
    assert order["customer_phone"] == CALLER
    assert [(x["name"], x["qty"]) for x in order["lines"]] == [("G Paneer Tikka", 2)]


async def test_the_spoken_total_is_the_menus_price_not_anything_the_model_sent(
    client: httpx.AsyncClient, seed: Seed, voice: dict[str, Any]
) -> None:
    body = order_body(voice, price=1, total=1, unit_price_paise=1)  # extra fields are ignored
    result = await call(client, voice, "place_order", body)
    (order,) = (
        await client.get(f"/v1/outlets/{seed.outlet_a}/staff/voice-orders", headers=manager(seed))
    ).json()
    assert order["lines"][0]["line_total_paise"] >= 2 * 32000 - 1  # menu price, not 1
    assert "Estimated total ₹" in result
    assert "₹1 " not in result


async def test_a_delivery_order_with_a_saved_address_links_customer_and_address(
    client: httpx.AsyncClient, voice: dict[str, Any], owner_engine: AsyncEngine
) -> None:
    saved = await call(client, voice, "save_address", {"phone": CALLER, "address": "1 Test Street"})
    address_id = saved.split("address_id=")[1].rstrip(".")
    result = await call(
        client,
        voice,
        "place_order",
        order_body(voice, fulfillment="delivery", address_id=address_id),
    )
    assert "for delivery" in result
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT o.customer_id, o.address_id::text, o.delivery_address_snapshot, o.source "
                    "FROM tab_order o WHERE o.source = 'voice'"
                )
            )
        ).one()
    assert row.customer_id is not None
    assert row.address_id == address_id
    assert row.delivery_address_snapshot == "1 Test Street"


async def test_a_delivery_order_with_a_new_address_saves_it_for_next_time(
    client: httpx.AsyncClient, voice: dict[str, Any]
) -> None:
    await call(
        client,
        voice,
        "place_order",
        order_body(voice, fulfillment="delivery", address="7 New Lane", name="Test Caller"),
    )
    result = await call(client, voice, "lookup_customer", {"phone": CALLER})
    assert "Known customer (Test Caller)" in result and '"7 New Lane"' in result


async def test_a_number_from_contact_phone_is_used_when_caller_id_is_missing(
    client: httpx.AsyncClient, voice: dict[str, Any]
) -> None:
    result = await call(
        client,
        voice,
        "place_order",
        order_body(voice, phone="anonymous", contact_phone="9999900303"),
    )
    assert result.startswith("ORDER SENT FOR CONFIRMATION")
    assert (await call(client, voice, "lookup_customer", {"phone": "9999900303"})).startswith(
        "Known customer"
    )


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"phone": "anonymous"}, "number is not available"),
        ({"fulfillment": "dine_in"}, "pickup or delivery"),
        ({"fulfillment": "delivery"}, "needs an address"),
        ({"items": [{"item_id": "not-a-uuid", "qty": 1}]}, "ids in the menu"),
        ({"items": [{"item_id": str(uuid.uuid4()), "qty": 1}]}, "not on this menu"),
        ({"items": []}, "no items"),
    ],
)
async def test_bad_orders_say_so_and_write_nothing(
    client: httpx.AsyncClient,
    voice: dict[str, Any],
    owner_engine: AsyncEngine,
    change: dict[str, Any],
    fragment: str,
) -> None:
    result = await call(client, voice, "place_order", {**order_body(voice), **change})
    assert result.startswith("ORDER NOT PLACED")
    assert fragment in result
    assert "Do not tell the caller an order was placed" in result
    async with owner_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM tab_order WHERE source = 'voice'")) == 0
        assert await conn.scalar(text("SELECT count(*) FROM tab WHERE opened_by = 'voice'")) == 0


async def test_another_callers_address_cannot_be_used(
    client: httpx.AsyncClient, voice: dict[str, Any], owner_engine: AsyncEngine
) -> None:
    other = await call(
        client, voice, "save_address", {"phone": "+919999900404", "address": "9 Other Street"}
    )
    other_id = other.split("address_id=")[1].rstrip(".")
    result = await call(
        client, voice, "place_order", order_body(voice, fulfillment="delivery", address_id=other_id)
    )
    assert result.startswith("ORDER NOT PLACED")
    assert "does not belong" in result
    async with owner_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM tab_order WHERE source = 'voice'")) == 0


async def test_a_repeated_tool_call_places_one_order(
    client: httpx.AsyncClient, seed: Seed, voice: dict[str, Any]
) -> None:
    body = order_body(voice, call_id="fixture-call-77")
    first = await call(client, voice, "place_order", body)
    second = await call(client, voice, "place_order", body)
    assert first == second
    pending = (
        await client.get(f"/v1/outlets/{seed.outlet_a}/staff/voice-orders", headers=manager(seed))
    ).json()
    assert len(pending) == 1
    assert pending[0]["call_id"] == "fixture-call-77"


async def test_a_different_order_in_the_same_call_is_a_second_order(
    client: httpx.AsyncClient, seed: Seed, voice: dict[str, Any]
) -> None:
    await call(client, voice, "place_order", order_body(voice, call_id="fixture-call-78"))
    other = order_body(voice, call_id="fixture-call-78")
    other["items"] = [{"item_id": voice["menu"].item["id"], "qty": 5}]
    await call(client, voice, "place_order", other)
    pending = (
        await client.get(f"/v1/outlets/{seed.outlet_a}/staff/voice-orders", headers=manager(seed))
    ).json()
    assert len(pending) == 2


async def test_a_failed_attempt_can_be_retried_after_the_problem_is_fixed(
    client: httpx.AsyncClient, seed: Seed, voice: dict[str, Any]
) -> None:
    bad = order_body(voice, call_id="fixture-call-79", fulfillment="delivery")
    assert (await call(client, voice, "place_order", bad)).startswith("ORDER NOT PLACED")
    fixed = {**bad, "address": "3 Retry Road"}
    assert (await call(client, voice, "place_order", fixed)).startswith("ORDER SENT")
    pending = (
        await client.get(f"/v1/outlets/{seed.outlet_a}/staff/voice-orders", headers=manager(seed))
    ).json()
    assert len(pending) == 1
