"""The WebSocket gateway, against a real server, Redis and Postgres. Guests see only
their own tab; staff see what their role needs; a reconnecting client resumes from the
last event id it saw."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from app.core.permissions import Role
from app.main import app
from app.realtime import gateway, scheduler
from app.realtime.bus import bus, outlet_channel
from tests.api.guest_helpers import FakeClock, Guest, new_guest, one, scan, table_token
from tests.api.helpers import Menu
from tests.conftest import Seed, hdr


@pytest.fixture
async def ws_url() -> AsyncIterator[str]:
    """The real app on a real port, in the test's own event loop so the database and
    Redis connections are shared with the test."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        await asyncio.sleep(0.01)
    yield f"ws://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit = True
    await task


async def open_socket(
    url: str, outlet_id: Any, token: str, last_event_id: int | None = None
) -> ClientConnection:
    ws = await connect(f"{url}/v1/outlets/{outlet_id}/ws")
    await ws.send(json.dumps({"type": "auth", "token": token, "last_event_id": last_event_id}))
    return ws


async def until_ready(ws: ClientConnection) -> list[dict[str, Any]]:
    """Everything sent before `ready`: the replay."""
    seen: list[dict[str, Any]] = []
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "ready":
            return seen
        seen.append(message)


async def next_message(ws: ClientConnection, timeout: float = 3) -> dict[str, Any]:
    return dict(json.loads(await asyncio.wait_for(ws.recv(), timeout)))


async def next_event(ws: ClientConnection, name: str, timeout: float = 3) -> dict[str, Any]:
    while True:
        message = await next_message(ws, timeout)
        if message.get("event") == name:
            return message


async def silent(ws: ClientConnection, seconds: float = 0.6) -> bool:
    """True when nothing arrives for a while (heartbeats are far apart in tests)."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(ws.recv(), seconds)
        return False
    return True


async def close_code(ws: ClientConnection) -> int:
    with pytest.raises(ConnectionClosed):
        await asyncio.wait_for(ws.recv(), 3)
    assert ws.close_code is not None
    return int(ws.close_code)


def staff_token(seed: Seed, user: uuid.UUID, role: Role, tenant: str = "a") -> str:
    return seed.token(user, role, tenant=tenant)


async def place(guest: Guest, menu: Menu, qty: int = 1) -> httpx.Response:
    r = await guest.order([one(menu.item, qty)])
    assert r.status_code == 201, r.text
    return r


# --- delivery and role filtering ------------------------------------------------


async def test_guest_hears_about_their_own_tab_only(
    client: httpx.AsyncClient, seed: Seed, env: Menu, ws_url: str
) -> None:
    mine = await new_guest(client, seed, "T1")
    other = await new_guest(client, seed, "T2")
    ws_mine = await open_socket(ws_url, mine.outlet_id, mine.token)
    ws_other = await open_socket(ws_url, other.outlet_id, other.token)
    assert await until_ready(ws_mine) == [] and await until_ready(ws_other) == []

    await place(mine, env)
    added = await next_event(ws_mine, "line_added")
    assert added["tab_id"] == mine.tab_id
    assert added["payload"]["item"] == "G Paneer Tikka"
    assert added["payload"]["unit_price_paise"] == 32000  # a guest sees their own prices
    assert (await next_event(ws_mine, "order_placed"))["payload"]["seq_no"] == 1
    assert await silent(ws_other)
    await ws_mine.close()
    await ws_other.close()


async def test_each_role_sees_what_it_needs(
    client: httpx.AsyncClient, seed: Seed, env: Menu, ws_url: str
) -> None:
    guest = await new_guest(client, seed)
    waiter = await open_socket(ws_url, seed.outlet_a, staff_token(seed, seed.waiter_a, Role.WAITER))
    manager = await open_socket(
        ws_url, seed.outlet_a, staff_token(seed, seed.manager_a, Role.MANAGER)
    )
    kitchen = await open_socket(
        ws_url, seed.outlet_a, staff_token(seed, seed.kitchen_a, Role.KITCHEN)
    )
    for ws in (waiter, manager, kitchen):
        await until_ready(ws)

    await place(guest, env, qty=2)
    await client.post(
        f"{guest.base}/service-requests", json={"type": "waiter"}, headers=guest.headers()
    )

    for ws in (waiter, manager):
        assert (await next_event(ws, "line_added"))["payload"]["line_total_paise"] == 64000
        assert (await next_event(ws, "service_requested"))["payload"]["type"] == "waiter"

    line = await next_event(kitchen, "line_added")
    assert line["payload"] == {
        "order_id": line["payload"]["order_id"],
        "line_id": line["payload"]["line_id"],
        "item": "G Paneer Tikka",
        "qty": 2,
        "modifiers": [],
    }
    placed = await next_event(kitchen, "order_placed")
    assert "total_paise" not in placed["payload"]
    assert await silent(kitchen)  # nothing about the waiter call
    for ws in (waiter, manager, kitchen):
        await ws.close()


async def test_every_connection_to_an_outlet_gets_the_message(
    client: httpx.AsyncClient, seed: Seed, env: Menu, ws_url: str
) -> None:
    guest = await new_guest(client, seed)
    sockets = [
        await open_socket(ws_url, seed.outlet_a, staff_token(seed, seed.waiter_a, Role.WAITER))
        for _ in range(3)
    ]
    for ws in sockets:
        await until_ready(ws)
    await place(guest, env)
    for ws in sockets:
        assert (await next_event(ws, "order_placed"))["tab_id"] == guest.tab_id
        await ws.close()


async def test_another_restaurant_hears_nothing(
    client: httpx.AsyncClient, seed: Seed, env: Menu, ws_url: str
) -> None:
    guest = await new_guest(client, seed)
    outsider = await open_socket(
        ws_url, seed.outlet_b, staff_token(seed, seed.manager_b, Role.MANAGER, "b")
    )
    await until_ready(outsider)
    await place(guest, env)
    assert await silent(outsider)
    await outsider.close()
    # And their token is no use on our outlet's channel.
    intruder = await open_socket(
        ws_url, seed.outlet_a, staff_token(seed, seed.manager_b, Role.MANAGER, "b")
    )
    assert await close_code(intruder) == gateway.CLOSE_UNAUTHORISED


# --- authentication ------------------------------------------------------------


async def test_connections_that_cannot_prove_who_they_are_are_closed(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    ws_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guest = await new_guest(client, seed)
    for token in ("garbage", "", seed.restaurant_a.hex + ".wrong"):
        ws = await open_socket(ws_url, guest.outlet_id, token)
        assert await close_code(ws) == gateway.CLOSE_UNAUTHORISED
    # A valid guest token on another outlet's channel.
    ws = await open_socket(ws_url, seed.outlet_b, guest.token)
    assert await close_code(ws) == gateway.CLOSE_UNAUTHORISED
    # Deactivated staff.
    ws = await open_socket(
        ws_url, seed.outlet_a, staff_token(seed, seed.inactive_waiter_a, Role.WAITER)
    )
    assert await close_code(ws) == gateway.CLOSE_UNAUTHORISED

    for bad in ('{"type": "auth"}', '{"type": "nope", "token": "x"}', "not json", '{"token": 5}'):
        ws = await connect(f"{ws_url}/v1/outlets/{guest.outlet_id}/ws")
        await ws.send(bad)
        assert await close_code(ws) == gateway.CLOSE_BAD_FRAME
    ws = await connect(f"{ws_url}/v1/outlets/{guest.outlet_id}/ws")
    await ws.send(json.dumps({"type": "auth", "token": guest.token, "last_event_id": "x"}))
    assert await close_code(ws) == gateway.CLOSE_BAD_FRAME

    monkeypatch.setattr(gateway, "AUTH_TIMEOUT_SECONDS", 0.2)
    silent_client = await connect(f"{ws_url}/v1/outlets/{guest.outlet_id}/ws")
    assert await close_code(silent_client) == gateway.CLOSE_BAD_FRAME


async def test_an_expired_session_cannot_connect(
    client: httpx.AsyncClient, seed: Seed, env: Menu, ws_url: str, fake_clock: FakeClock
) -> None:
    guest = await new_guest(client, seed)
    fake_clock.advance(6 * 3600 + 1)
    ws = await open_socket(ws_url, guest.outlet_id, guest.token)
    assert await close_code(ws) == gateway.CLOSE_UNAUTHORISED


async def test_heartbeat_pings_and_ends_a_lapsed_guest_session(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    ws_url: str,
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway, "HEARTBEAT_SECONDS", 0.15)
    guest = await new_guest(client, seed)
    waiter = await open_socket(ws_url, seed.outlet_a, staff_token(seed, seed.waiter_a, Role.WAITER))
    ws = await open_socket(ws_url, guest.outlet_id, guest.token)
    await until_ready(ws)
    await until_ready(waiter)
    assert (await next_message(ws))["type"] == "ping"
    assert (await next_message(waiter))["type"] == "ping"  # staff sessions never lapse on a timer
    fake_clock.advance(6 * 3600 + 1)
    assert await close_code(ws) == gateway.CLOSE_UNAUTHORISED
    await waiter.close()


async def test_a_guests_socket_closes_when_their_tab_ends(
    client: httpx.AsyncClient, seed: Seed, env: Menu, ws_url: str
) -> None:
    guest = await new_guest(client, seed)
    ws = await open_socket(ws_url, guest.outlet_id, guest.token)
    waiter = await open_socket(ws_url, seed.outlet_a, staff_token(seed, seed.waiter_a, Role.WAITER))
    await until_ready(ws)
    await until_ready(waiter)
    await bus.publish(
        outlet_channel(uuid.UUID(guest.outlet_id)),
        {
            "id": 10**12,
            "tab_id": guest.tab_id,
            "at": "2026-09-18T20:00:00+00:00",
            "event": "closed",
            "actor_type": "staff",
            "payload": {},
        },
    )
    assert (await next_message(ws))["event"] == "closed"
    assert await close_code(ws) == gateway.CLOSE_TAB_ENDED
    assert (await next_message(waiter))["event"] == "closed"  # staff stay connected
    await waiter.close()


# --- resume --------------------------------------------------------------------


async def test_a_fresh_connection_replays_nothing_but_a_reconnect_resumes(
    client: httpx.AsyncClient, seed: Seed, env: Menu, ws_url: str
) -> None:
    guest = await new_guest(client, seed)
    await place(guest, env)

    ws = await open_socket(ws_url, guest.outlet_id, guest.token)
    assert await until_ready(ws) == []  # first connect: fetch state over REST instead
    await place(guest, env)
    seen = [await next_event(ws, "order_placed")]
    last = seen[-1]["id"]
    await ws.close()

    await place(guest, env)  # happens while the client is away
    await place(guest, env)
    ws = await open_socket(ws_url, guest.outlet_id, guest.token, last_event_id=last)
    replay = await until_ready(ws)
    assert all(m["id"] > last for m in replay)
    assert [m["payload"]["seq_no"] for m in replay if m["event"] == "order_placed"] == [3, 4]
    assert [m["id"] for m in replay] == sorted(m["id"] for m in replay)

    # Live events after the replay carry on without repeating any of it.
    await place(guest, env)
    live = await next_event(ws, "order_placed")
    assert live["payload"]["seq_no"] == 5 and live["id"] > replay[-1]["id"]
    await ws.close()


async def test_resume_applies_the_same_role_filter(
    client: httpx.AsyncClient, seed: Seed, env: Menu, ws_url: str
) -> None:
    guest = await new_guest(client, seed)
    await place(guest, env)
    await client.post(
        f"{guest.base}/service-requests", json={"type": "water"}, headers=guest.headers()
    )
    kitchen = await open_socket(
        ws_url, seed.outlet_a, staff_token(seed, seed.kitchen_a, Role.KITCHEN), last_event_id=0
    )
    replay = await until_ready(kitchen)
    assert {m["event"] for m in replay} == {"line_added", "order_placed"}
    assert all("price" not in json.dumps(m["payload"]) for m in replay)
    await kitchen.close()

    waiter = await open_socket(
        ws_url, seed.outlet_a, staff_token(seed, seed.waiter_a, Role.WAITER), last_event_id=0
    )
    assert "service_requested" in {m["event"] for m in await until_ready(waiter)}
    await waiter.close()

    # A guest never gets another tab's history, even asking from the start.
    other = await new_guest(client, seed, "T2")
    ws = await open_socket(ws_url, other.outlet_id, other.token, last_event_id=0)
    assert [m["event"] for m in await until_ready(ws)] == ["opened"]
    await ws.close()


async def test_missing_too_much_asks_the_client_to_resync(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    ws_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway, "REPLAY_LIMIT", 2)
    guest = await new_guest(client, seed)
    await place(guest, env)
    ws = await open_socket(ws_url, guest.outlet_id, guest.token, last_event_id=0)
    assert [m["type"] for m in await until_ready(ws)] == ["resync"]
    await place(guest, env)
    assert (await next_event(ws, "order_placed"))["payload"]["seq_no"] == 2
    await ws.close()


# --- publishing ----------------------------------------------------------------


async def test_a_rolled_back_request_tells_nobody(
    client: httpx.AsyncClient, seed: Seed, env: Menu, ws_url: str
) -> None:
    guest = await new_guest(client, seed)
    ws = await open_socket(ws_url, guest.outlet_id, guest.token)
    await until_ready(ws)
    refused = await guest.order([{"menu_item_id": str(uuid.uuid4()), "qty": 1}])
    assert refused.status_code == 422
    assert await silent(ws)
    await ws.close()


async def test_a_redis_outage_does_not_fail_the_request_and_resume_recovers(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    ws_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guest = await new_guest(client, seed)

    async def down(*_: Any, **__: Any) -> None:
        raise ConnectionError("redis is down")

    monkeypatch.setattr(bus, "publish", down)
    placed = await place(guest, env)
    monkeypatch.undo()

    ws = await open_socket(ws_url, guest.outlet_id, guest.token, last_event_id=0)
    replay = await until_ready(ws)
    assert placed.json()["id"] in json.dumps(replay)
    await ws.close()


async def test_the_undo_window_closing_pushes_order_accepted(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    ws_url: str,
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler, "ENABLED", True)
    monkeypatch.setattr(scheduler, "DELAY_SECONDS", 0.1)
    guest = await new_guest(client, seed)
    kitchen = await open_socket(
        ws_url, seed.outlet_a, staff_token(seed, seed.kitchen_a, Role.KITCHEN)
    )
    await until_ready(kitchen)
    await place(guest, env)
    fake_clock.advance(61)  # the undo window has closed by the time the timer fires
    accepted = await next_event(kitchen, "order_accepted")
    assert accepted["actor_type"] == "system" and accepted["payload"]["auto"] is True
    await scheduler.cancel_all()
    await kitchen.close()


async def test_a_timer_that_fires_early_accepts_nothing(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    ws_url: str,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler, "ENABLED", True)
    monkeypatch.setattr(scheduler, "DELAY_SECONDS", 0.05)
    guest = await new_guest(client, seed)
    placed = (await place(guest, env)).json()
    await asyncio.sleep(0.4)  # timer has fired, but the clock never moved past 60 s
    await scheduler.cancel_all()
    async with owner_engine.connect() as conn:
        status = await conn.scalar(
            text("SELECT status FROM tab_order WHERE id = :o"), {"o": uuid.UUID(placed["id"])}
        )
    assert status == "placed"


async def test_a_failing_timer_is_survivable(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(scheduler, "ENABLED", True)
    monkeypatch.setattr(scheduler, "DELAY_SECONDS", 0.05)
    monkeypatch.setattr(scheduler, "tenant_session", broken)
    guest = await new_guest(client, seed)
    await place(guest, env)
    await asyncio.sleep(0.3)
    await scheduler.cancel_all()
    assert (await guest.tab())["rounds"][0]["status"] == "placed"


async def test_qr_landing_announces_a_new_tab_to_staff(
    client: httpx.AsyncClient, seed: Seed, env: Menu, ws_url: str
) -> None:
    waiter = await open_socket(ws_url, seed.outlet_a, staff_token(seed, seed.waiter_a, Role.WAITER))
    await until_ready(waiter)
    r = await scan(client, await table_token(client, seed, "T2"))
    opened = await next_event(waiter, "opened")
    assert opened["tab_id"] == r.json()["tab_id"] and opened["payload"] == {"table": "T2"}
    await waiter.close()


async def test_confirming_a_tab_is_pushed_to_the_guest(
    client: httpx.AsyncClient, seed: Seed, env: Menu, ws_url: str
) -> None:
    await client.patch(
        f"{env.base}/settings",
        json={"waiter_confirm_mode": True},
        headers=hdr(seed.token(seed.owner_a, Role.OWNER)),
    )
    guest = await new_guest(client, seed)
    ws = await open_socket(ws_url, guest.outlet_id, guest.token)
    await until_ready(ws)
    await client.post(
        f"{guest.base}/confirm", headers=hdr(staff_token(seed, seed.waiter_a, Role.WAITER))
    )
    assert (await next_event(ws, "confirmed"))["actor_type"] == "staff"
    await ws.close()
