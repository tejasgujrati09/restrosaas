"""Phone orders wait for a person: never auto-accepted, accepted or rejected by a manager or
owner, invisible to other tenants and to roles that may not act. Fixture data only."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.ordering import CartLine
from app.core.permissions import Role
from app.db.session import tenant_session
from app.domains.voice.models import Customer, CustomerAddress
from app.domains.voice.service import place_voice_order
from app.errors import ApiError
from tests.api.guest_helpers import (
    FakeClock,
    kitchen,
    manager,
    new_guest,
    one,
    staff,
    waiter,
    wipe_tabs,
)
from tests.api.helpers import Menu
from tests.conftest import Seed, hdr, new_phone

pytestmark = pytest.mark.usefixtures("fake_clock")


@dataclass
class Placed:
    order_id: uuid.UUID
    tab_id: uuid.UUID
    customer_id: uuid.UUID
    address_id: uuid.UUID


@pytest.fixture
async def voice_env(
    env: Menu, seed: Seed, owner_engine: AsyncEngine
) -> AsyncIterator[dict[str, Any]]:
    yield {"menu": env}
    await wipe_tabs(owner_engine, seed)
    async with owner_engine.begin() as conn:
        for table in ("customer_address", "customer"):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE restaurant_id = :r"), {"r": seed.restaurant_a}
            )


async def _place(
    seed: Seed,
    menu: Menu,
    clock: FakeClock,
    *,
    fulfillment: str = "delivery",
    qty: int = 2,
    call_id: str = "fixture-call-1",
) -> Placed:
    async with tenant_session(seed.restaurant_a) as session:
        customer = Customer(
            restaurant_id=seed.restaurant_a,
            phone=new_phone(),
            name="Test Caller",
            created_at=clock.now,
        )
        session.add(customer)
        await session.flush()
        address = CustomerAddress(
            restaurant_id=seed.restaurant_a,
            customer_id=customer.id,
            address_text="1 Test Street, Testville",
            is_preferred=True,
            created_at=clock.now,
        )
        session.add(address)
        await session.flush()
        placed = await place_voice_order(
            session,
            restaurant_id=seed.restaurant_a,
            outlet_id=seed.outlet_a,
            customer=customer,
            address=address,
            fulfillment=fulfillment,
            cart=[CartLine(uuid.UUID(menu.item["id"]), qty, ())],
            call_id=call_id,
            now=clock.now,
        )
        return Placed(placed.order.id, placed.order.tab_id, customer.id, address.id)


def _base(seed: Seed) -> str:
    return f"/v1/outlets/{seed.outlet_a}/staff/voice-orders"


async def _tickets(client: httpx.AsyncClient, seed: Seed) -> list[dict[str, Any]]:
    r = await client.get(f"/v1/outlets/{seed.outlet_a}/tickets", headers=kitchen(seed))
    assert r.status_code == 200, r.text
    return list(r.json()["queue"])


async def test_a_phone_order_is_placed_and_never_auto_accepted(
    client: httpx.AsyncClient, seed: Seed, voice_env: dict[str, Any], fake_clock: FakeClock
) -> None:
    placed = await _place(seed, voice_env["menu"], fake_clock)
    fake_clock.advance(3600)  # far past any undo window

    pending = await client.get(_base(seed), headers=manager(seed))
    assert pending.status_code == 200, pending.text
    (order,) = pending.json()
    assert order["order_id"] == str(placed.order_id)
    assert order["status"] == "placed"

    (ticket,) = await _tickets(client, seed)  # reading the queue must not accept it either
    assert ticket["can_start"] is False
    assert ticket["holding_until"] is None
    assert ticket["source"] == "voice"
    start = await client.post(
        f"/v1/outlets/{seed.outlet_a}/tickets/{ticket['id']}/start", headers=kitchen(seed)
    )
    assert start.status_code == 409


async def test_pending_list_shows_who_what_and_where(
    client: httpx.AsyncClient, seed: Seed, voice_env: dict[str, Any], fake_clock: FakeClock
) -> None:
    await _place(seed, voice_env["menu"], fake_clock, qty=2, call_id="fixture-call-9")
    (order,) = (await client.get(_base(seed), headers=manager(seed))).json()
    assert order["customer_name"] == "Test Caller"
    assert order["fulfillment_type"] == "delivery"
    assert order["delivery_address"] == "1 Test Street, Testville"
    assert order["call_id"] == "fixture-call-9"
    assert [(line["name"], line["qty"]) for line in order["lines"]] == [("G Paneer Tikka", 2)]
    assert order["total_paise"] == sum(line["line_total_paise"] for line in order["lines"])


async def test_pickup_order_records_no_address(
    client: httpx.AsyncClient, seed: Seed, voice_env: dict[str, Any], fake_clock: FakeClock
) -> None:
    await _place(seed, voice_env["menu"], fake_clock, fulfillment="pickup")
    (order,) = (await client.get(_base(seed), headers=manager(seed))).json()
    assert order["fulfillment_type"] == "pickup"
    assert order["delivery_address"] is None


async def test_manager_accepts_and_the_kitchen_can_then_start(
    client: httpx.AsyncClient, seed: Seed, voice_env: dict[str, Any], fake_clock: FakeClock
) -> None:
    placed = await _place(seed, voice_env["menu"], fake_clock)
    accepted = await client.post(f"{_base(seed)}/{placed.order_id}/accept", headers=manager(seed))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"

    (ticket,) = await _tickets(client, seed)
    assert ticket["can_start"] is True
    started = await client.post(
        f"/v1/outlets/{seed.outlet_a}/tickets/{ticket['id']}/start", headers=kitchen(seed)
    )
    assert started.status_code == 200, started.text
    assert (await client.get(_base(seed), headers=manager(seed))).json() == []


async def test_owner_can_accept_too(
    client: httpx.AsyncClient, seed: Seed, voice_env: dict[str, Any], fake_clock: FakeClock
) -> None:
    placed = await _place(seed, voice_env["menu"], fake_clock)
    r = await client.post(
        f"{_base(seed)}/{placed.order_id}/accept", headers=staff(seed, seed.owner_a, Role.OWNER)
    )
    assert r.status_code == 200, r.text


async def test_accepting_twice_is_refused_and_a_replayed_key_is_not(
    client: httpx.AsyncClient, seed: Seed, voice_env: dict[str, Any], fake_clock: FakeClock
) -> None:
    placed = await _place(seed, voice_env["menu"], fake_clock)
    url = f"{_base(seed)}/{placed.order_id}/accept"
    key = {"Idempotency-Key": str(uuid.uuid4())}
    first = await client.post(url, headers={**manager(seed), **key})
    replay = await client.post(url, headers={**manager(seed), **key})
    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    again = await client.post(url, headers=manager(seed))
    assert again.status_code == 409
    assert again.json()["code"] == "order_not_pending"


async def test_reject_cancels_the_round_with_a_reason_and_withdraws_the_ticket(
    client: httpx.AsyncClient,
    seed: Seed,
    voice_env: dict[str, Any],
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    placed = await _place(seed, voice_env["menu"], fake_clock)
    r = await client.post(
        f"{_base(seed)}/{placed.order_id}/reject",
        json={"reason": "Kitchen is closed"},
        headers=manager(seed),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    assert await _tickets(client, seed) == []
    assert (await client.get(_base(seed), headers=manager(seed))).json() == []
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT actor_type, reason FROM tab_event "
                    "WHERE tab_id = :t AND event = 'order_cancelled'"
                ),
                {"t": placed.tab_id},
            )
        ).one()
    assert (row.actor_type, row.reason) == ("staff", "Kitchen is closed")
    again = await client.post(f"{_base(seed)}/{placed.order_id}/accept", headers=manager(seed))
    assert again.status_code == 409


async def test_reject_needs_a_reason(
    client: httpx.AsyncClient, seed: Seed, voice_env: dict[str, Any], fake_clock: FakeClock
) -> None:
    placed = await _place(seed, voice_env["menu"], fake_clock)
    r = await client.post(
        f"{_base(seed)}/{placed.order_id}/reject", json={"reason": ""}, headers=manager(seed)
    )
    assert r.status_code == 422


@pytest.mark.parametrize("who", ["waiter", "kitchen"])
async def test_waiter_and_kitchen_cannot_see_or_act_on_phone_orders(
    client: httpx.AsyncClient,
    seed: Seed,
    voice_env: dict[str, Any],
    fake_clock: FakeClock,
    who: str,
) -> None:
    placed = await _place(seed, voice_env["menu"], fake_clock)
    headers = waiter(seed) if who == "waiter" else kitchen(seed)
    assert (await client.get(_base(seed), headers=headers)).status_code == 403
    r = await client.post(f"{_base(seed)}/{placed.order_id}/accept", headers=headers)
    assert r.status_code == 403
    r = await client.post(
        f"{_base(seed)}/{placed.order_id}/reject", json={"reason": "no"}, headers=headers
    )
    assert r.status_code == 403


async def test_another_restaurants_manager_cannot_reach_the_order(
    client: httpx.AsyncClient, seed: Seed, voice_env: dict[str, Any], fake_clock: FakeClock
) -> None:
    placed = await _place(seed, voice_env["menu"], fake_clock)
    other = hdr(seed.token(seed.manager_b, Role.MANAGER, tenant="b"))
    assert (await client.get(_base(seed), headers=other)).status_code == 403
    r = await client.post(f"{_base(seed)}/{placed.order_id}/accept", headers=other)
    assert r.status_code == 403


async def test_the_round_records_where_it_came_from(
    seed: Seed, voice_env: dict[str, Any], fake_clock: FakeClock, owner_engine: AsyncEngine
) -> None:
    placed = await _place(seed, voice_env["menu"], fake_clock, call_id="fixture-call-7")
    async with owner_engine.connect() as conn:
        tab = (
            await conn.execute(
                text("SELECT opened_by, table_id, status FROM tab WHERE id = :t"),
                {"t": placed.tab_id},
            )
        ).one()
        order = (
            await conn.execute(
                text(
                    "SELECT source, fulfillment_type, customer_id, address_id, "
                    "delivery_address_snapshot, external_call_id, status "
                    "FROM tab_order WHERE id = :o"
                ),
                {"o": placed.order_id},
            )
        ).one()
        events = (
            await conn.execute(
                text(
                    "SELECT event, actor_type, payload FROM tab_event "
                    "WHERE tab_id = :t AND event IN ('opened', 'order_placed') ORDER BY at, event"
                ),
                {"t": placed.tab_id},
            )
        ).all()
    assert tuple(tab) == ("voice", None, "open")
    assert order.source == "voice"
    assert order.fulfillment_type == "delivery"
    assert order.customer_id == placed.customer_id
    assert order.address_id == placed.address_id
    assert order.delivery_address_snapshot == "1 Test Street, Testville"
    assert order.external_call_id == "fixture-call-7"
    assert order.status == "placed"
    assert {e.event: e.actor_type for e in events} == {"opened": "system", "order_placed": "system"}
    placed_event = next(e for e in events if e.event == "order_placed")
    assert placed_event.payload["channel"] == "voice"
    assert placed_event.payload["call_id"] == "fixture-call-7"


async def test_editing_the_saved_address_does_not_change_an_existing_order(
    client: httpx.AsyncClient,
    seed: Seed,
    voice_env: dict[str, Any],
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    placed = await _place(seed, voice_env["menu"], fake_clock)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE customer_address SET address_text = '99 Changed Road' WHERE id = :a"),
            {"a": placed.address_id},
        )
    (order,) = (await client.get(_base(seed), headers=manager(seed))).json()
    assert order["delivery_address"] == "1 Test Street, Testville"


@pytest.mark.parametrize(
    ("fulfillment", "qty", "with_address", "code"),
    [
        ("dine_in", 1, True, "invalid_fulfillment"),
        ("delivery", 1, False, "address_required"),
        ("pickup", 0, True, "invalid_quantity"),
    ],
)
async def test_invalid_orders_are_refused_and_write_nothing(
    seed: Seed,
    voice_env: dict[str, Any],
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
    fulfillment: str,
    qty: int,
    with_address: bool,
    code: str,
) -> None:
    menu: Menu = voice_env["menu"]
    with pytest.raises(ApiError) as caught:
        async with tenant_session(seed.restaurant_a) as session:
            customer = Customer(
                restaurant_id=seed.restaurant_a,
                phone=new_phone(),
                name=None,
                created_at=fake_clock.now,
            )
            session.add(customer)
            await session.flush()
            address = None
            if with_address:
                address = CustomerAddress(
                    restaurant_id=seed.restaurant_a,
                    customer_id=customer.id,
                    address_text="2 Test Street",
                    created_at=fake_clock.now,
                )
                session.add(address)
                await session.flush()
            await place_voice_order(
                session,
                restaurant_id=seed.restaurant_a,
                outlet_id=seed.outlet_a,
                customer=customer,
                address=address,
                fulfillment=fulfillment,
                cart=[CartLine(uuid.UUID(menu.item["id"]), qty, ())],
                call_id=None,
                now=fake_clock.now,
            )
    assert caught.value.code == code
    async with owner_engine.connect() as conn:
        count = await conn.scalar(
            text("SELECT count(*) FROM tab WHERE restaurant_id = :r AND opened_by = 'voice'"),
            {"r": seed.restaurant_a},
        )
    assert count == 0


async def test_an_unknown_item_is_refused(
    seed: Seed, voice_env: dict[str, Any], fake_clock: FakeClock
) -> None:
    with pytest.raises(ApiError) as caught:
        async with tenant_session(seed.restaurant_a) as session:
            customer = Customer(
                restaurant_id=seed.restaurant_a,
                phone=new_phone(),
                name=None,
                created_at=fake_clock.now,
            )
            session.add(customer)
            await session.flush()
            await place_voice_order(
                session,
                restaurant_id=seed.restaurant_a,
                outlet_id=seed.outlet_a,
                customer=customer,
                address=None,
                fulfillment="pickup",
                cart=[CartLine(uuid.uuid4(), 1, ())],
                call_id=None,
                now=fake_clock.now,
            )
    assert caught.value.code == "unknown_item"


async def test_a_guest_order_is_still_auto_accepted(
    client: httpx.AsyncClient, seed: Seed, voice_env: dict[str, Any], fake_clock: FakeClock
) -> None:
    """The exclusion is for phone orders only: QR orders keep their timer."""
    guest = await new_guest(client, seed)
    placed = await guest.order([one(voice_env["menu"].item)])
    assert placed.status_code in (200, 201), placed.text
    fake_clock.advance(timedelta(minutes=5).total_seconds())
    assert (await guest.tab())["rounds"][0]["status"] == "accepted"
