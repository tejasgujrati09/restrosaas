"""The owner's Orders screen: every source in one list, real statuses grouped into tabs,
counts that match the rows, a timeline made only of recorded moments, one restaurant never
seeing another's orders, and a new phone order reaching the owner live."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.permissions import Role
from tests.api.conftest import VoiceJobs
from tests.api.guest_helpers import (
    FakeClock,
    floor,
    kitchen,
    manager,
    new_guest,
    one,
    staff,
    waiter,
)
from tests.api.helpers import Menu
from tests.api.test_realtime import next_event, open_socket, until_ready, ws_url  # noqa: F401
from tests.api.test_voice_agent import _key, _tool, _turn_on
from tests.conftest import Seed, hdr
from tests.voice_fakes import FakeVoicePlatform

pytestmark = pytest.mark.usefixtures("fake_clock")

PHONE = "+919999900707"


def _owner(seed: Seed) -> dict[str, str]:
    return staff(seed, seed.owner_a, Role.OWNER)


def _url(seed: Seed, suffix: str = "") -> str:
    return f"/v1/outlets/{seed.outlet_a}/staff/orders{suffix}"


async def _orders(
    client: httpx.AsyncClient, seed: Seed, who: dict[str, str] | None = None, **params: Any
) -> dict[str, Any]:
    r = await client.get(_url(seed), params=params, headers=who or _owner(seed))
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _counts(body: dict[str, Any]) -> tuple[int, int, int, int, int]:
    c = body["counts"]
    return (c["new"], c["in_progress"], c["ready"], c["completed"], c["cancelled"])


async def _phone_order(
    client: httpx.AsyncClient, fake: FakeVoicePlatform, env: Menu, **extra: Any
) -> None:
    body = {
        "phone": PHONE,
        "name": "Rahul",
        "fulfillment": "pickup",
        "items": [{"item_id": env.item["id"], "qty": 2}],
        **extra,
    }
    r = await _tool(client, _key(fake), "place_order", body)
    assert r.status_code == 200 and r.json()["result"].startswith("ORDER SENT"), r.text


# ---- empty, permissions, isolation --------------------------------------------------------


async def test_an_outlet_with_no_orders_says_so(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    body = await _orders(client, seed)
    assert _counts(body) == (0, 0, 0, 0, 0)
    assert body["orders"] == [] and body["earlier_open"] == 0 and body["has_more"] is False


@pytest.mark.parametrize("who", ["waiter", "kitchen"])
async def test_only_owner_and_manager_can_open_the_orders_screen(
    client: httpx.AsyncClient, seed: Seed, env: Menu, who: str
) -> None:
    headers = waiter(seed) if who == "waiter" else kitchen(seed)
    assert (await client.get(_url(seed), headers=headers)).status_code == 403
    assert (await client.get(_url(seed, f"/{uuid.uuid4()}"), headers=headers)).status_code == 403
    assert (await client.get(_url(seed), headers=manager(seed))).status_code == 200
    assert (await client.get(_url(seed))).status_code == 401


async def test_one_restaurant_never_sees_anothers_orders(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item, 1)])).json()
    order_id = placed["order_id"] if "order_id" in placed else placed["id"]
    b = {"Authorization": f"Bearer {seed.token(seed.owner_b, Role.OWNER, tenant='b')}"}

    assert (await client.get(_url(seed), headers=b)).status_code in (403, 404)  # A's outlet
    assert (await client.get(_url(seed, f"/{order_id}"), headers=b)).status_code in (403, 404)
    own = await client.get(f"/v1/outlets/{seed.outlet_b}/staff/orders", headers=b)
    assert own.status_code == 200 and own.json()["orders"] == []
    assert _counts(own.json()) == (0, 0, 0, 0, 0)
    inside = await client.get(
        f"/v1/outlets/{seed.outlet_b}/staff/orders/{order_id}", headers=b
    )  # A's order under B's own outlet
    assert inside.status_code == 404
    assert (await _orders(client, seed))["counts"]["new"] == 1  # and A still sees it


# ---- every source, one list ---------------------------------------------------------------


async def test_qr_and_phone_orders_appear_together_and_are_told_apart(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _turn_on(client, seed, jobs)
    g = await new_guest(client, seed)
    await g.order([one(env.item, 1)])
    await _phone_order(client, voice_platform, env)

    body = await _orders(client, seed, group="new")
    assert _counts(body) == (2, 0, 0, 0, 0)
    by_source = {o["source"]: o for o in body["orders"]}
    assert set(by_source) == {"customer", "voice"}
    qr, phone = by_source["customer"], by_source["voice"]
    assert qr["table_label"] == "T1" and qr["fulfillment_type"] == "dine_in"
    assert phone["table_label"] is None and phone["fulfillment_type"] == "pickup"
    assert (phone["customer_name"], phone["customer_phone"]) == ("Rahul", PHONE)
    assert phone["items"] == [{"name": env.item["name"], "qty": 2}]
    assert phone["total_paise"] == 2 * 32000
    assert len(phone["short_id"]) == 6 and phone["id"].upper().startswith(phone["short_id"])

    voice_only = await _orders(client, seed, source="voice")
    assert [o["source"] for o in voice_only["orders"]] == ["voice"]
    assert _counts(voice_only) == (1, 0, 0, 0, 0)  # counts follow the filter too


# ---- an order's life across the tabs, and its timeline -------------------------------------


async def test_a_phone_order_moves_through_every_tab_with_a_true_timeline(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE app_user SET name = 'Asha' WHERE id = :u"), {"u": seed.manager_a}
        )
    await _turn_on(client, seed, jobs)
    await _phone_order(client, voice_platform, env)
    row = (await _orders(client, seed))["orders"][0]
    detail = (await client.get(_url(seed, f"/{row['id']}"), headers=_owner(seed))).json()
    assert detail["actions"] == ["accept", "reject"] and detail["group"] == "new"
    assert [t["label"] for t in detail["timeline"]] == ["Order received"]

    fake_clock.advance(30)
    r = await client.post(
        f"/v1/outlets/{seed.outlet_a}/staff/voice-orders/{row['id']}/accept", headers=manager(seed)
    )
    assert r.status_code == 200
    body = await _orders(client, seed)
    assert _counts(body) == (0, 1, 0, 0, 0) and body["orders"] == []  # tab 'new' is now empty
    assert (await _orders(client, seed, group="in_progress"))["orders"][0]["id"] == row["id"]

    queue = (await client.get(f"/v1/outlets/{seed.outlet_a}/tickets", headers=kitchen(seed))).json()
    ticket_id = queue["queue"][0]["id"]
    fake_clock.advance(60)
    for verb in ("start", "ready"):
        fake_clock.advance(120)
        done = await client.post(
            f"/v1/outlets/{seed.outlet_a}/tickets/{ticket_id}/{verb}", headers=kitchen(seed)
        )
        assert done.status_code == 200, done.text
    assert _counts(await _orders(client, seed)) == (0, 0, 1, 0, 0)
    ready = (await client.get(_url(seed, f"/{row['id']}"), headers=_owner(seed))).json()
    assert ready["actions"] == ["serve"]

    fake_clock.advance(90)
    served = await client.post(
        f"{floor(seed)}/tabs/{ready['tab_id']}/orders/{row['id']}/serve",
        json={},
        headers=_owner(seed),
    )
    assert served.status_code == 200, served.text
    assert _counts(await _orders(client, seed)) == (0, 0, 0, 1, 0)

    final = (await client.get(_url(seed, f"/{row['id']}"), headers=_owner(seed))).json()
    assert final["status"] == "served" and final["actions"] == []
    labels = [t["label"] for t in final["timeline"]]
    assert labels[0] == "Order received" and labels[1] == "Accepted by staff"
    assert labels[-1] == "Served"
    assert {"Preparing", "Ready"} <= set(labels)
    times = [t["at"] for t in final["timeline"]]
    assert times == sorted(times)  # in the order it happened
    assert final["timeline"][1]["by"] == "Asha"  # who accepted it is on record
    (ticket,) = final["tickets"]
    assert ticket["started_at"] and ticket["ready_at"]


async def test_a_rejected_phone_order_lands_in_cancelled_with_its_reason(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _turn_on(client, seed, jobs)
    await _phone_order(client, voice_platform, env)
    row = (await _orders(client, seed))["orders"][0]
    r = await client.post(
        f"/v1/outlets/{seed.outlet_a}/staff/voice-orders/{row['id']}/reject",
        json={"reason": "Out of stock"},
        headers=manager(seed),
    )
    assert r.status_code == 200, r.text
    assert _counts(await _orders(client, seed)) == (0, 0, 0, 0, 1)
    detail = (await client.get(_url(seed, f"/{row['id']}"), headers=_owner(seed))).json()
    assert detail["group"] == "cancelled" and detail["actions"] == []
    last = detail["timeline"][-1]
    assert last["label"] == "Cancelled" and last["reason"] == "Out of stock"


async def test_order_detail_shows_lines_notes_modifiers_and_an_estimated_total(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    await g.order([one(env.item, 3, note="less oil")])
    row = (await _orders(client, seed))["orders"][0]
    d = (await client.get(_url(seed, f"/{row['id']}"), headers=_owner(seed))).json()
    assert d["source"] == "customer" and d["table_label"] == "T1" and d["tab_status"] == "open"
    (line,) = d["lines"]
    assert (line["name"], line["qty"], line["notes"]) == (env.item["name"], 3, "less oil")
    assert line["line_total_paise"] == 3 * line["unit_price_paise"]
    assert d["pricing"]["items_paise"] == line["line_total_paise"]
    assert d["pricing"]["taxes_included"] is True  # prices here contain the tax; it is not added on
    assert d["pricing"]["estimated_total_paise"] >= d["pricing"]["items_paise"] - 1
    assert d["actions"] == []  # a QR order is accepted by the system; nothing to offer
    assert d["timeline"][0]["label"] == "Order received"
    assert "Accepted" not in [t["label"] for t in d["timeline"]]  # nothing is made up


async def test_an_unknown_order_is_a_404(client: httpx.AsyncClient, seed: Seed, env: Menu) -> None:
    r = await client.get(_url(seed, f"/{uuid.uuid4()}"), headers=_owner(seed))
    assert r.status_code == 404


# ---- search and filters -------------------------------------------------------------------


async def test_search_by_order_id_customer_phone_and_table(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
) -> None:
    await _turn_on(client, seed, jobs)
    g = await new_guest(client, seed)
    await g.order([one(env.item, 1)])
    await _phone_order(client, voice_platform, env)
    every = (await _orders(client, seed))["orders"]
    phone = next(o for o in every if o["source"] == "voice")

    for q, expected in (
        (phone["short_id"], "voice"),
        ("#" + phone["short_id"].lower(), "voice"),
        ("rahul", "voice"),
        ("9999900707", "voice"),
        ("t1", "customer"),
    ):
        found = (await _orders(client, seed, q=q))["orders"]
        assert [o["source"] for o in found] == [expected], q
    assert (await _orders(client, seed, q="nobody"))["orders"] == []


async def test_filter_by_table_and_by_who_placed_it(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed, "T1")
    await g.order([one(env.item, 1)])
    tables = (await client.get(f"/v1/outlets/{seed.outlet_a}/tables", headers=_owner(seed))).json()
    t1 = next(t["id"] for t in tables if t["label"] == "T1")
    t2 = next(t["id"] for t in tables if t["label"] != "T1")
    assert len((await _orders(client, seed, table_id=t1))["orders"]) == 1
    assert (await _orders(client, seed, table_id=t2))["orders"] == []
    assert (await _orders(client, seed, placed_by=str(uuid.uuid4())))["orders"] == []


# ---- one date window for counts and list ---------------------------------------------------


async def test_counts_and_rows_share_the_date_and_older_open_orders_are_flagged_not_mixed(
    client: httpx.AsyncClient, seed: Seed, env: Menu, fake_clock: FakeClock
) -> None:
    g = await new_guest(client, seed)
    await g.order([one(env.item, 1)])
    first = fake_clock.now.astimezone().date()
    fake_clock.advance(2 * 24 * 3600)  # two days later

    today = await _orders(client, seed)
    assert _counts(today) == (0, 0, 0, 0, 0) and today["orders"] == []
    assert today["earlier_open"] == 1  # still waiting from before the window; not counted here

    span = await _orders(
        client, seed, date_from=(first - timedelta(days=1)).isoformat(), date_to=today["date_to"]
    )
    assert span["counts"]["new"] + span["counts"]["in_progress"] == 1
    assert len(span["orders"]) + sum(_counts(span)[1:]) >= 1
    assert span["earlier_open"] == 0  # nothing older than that window is still open


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-09-10", "date_to": "2026-09-01"},
        {"date_from": "2026-01-01", "date_to": "2026-09-30"},
    ],
)
async def test_a_backwards_or_huge_range_is_refused(
    client: httpx.AsyncClient, seed: Seed, env: Menu, params: dict[str, str]
) -> None:
    r = await client.get(_url(seed), params=params, headers=_owner(seed))
    assert r.status_code == 422


async def test_a_bad_status_group_or_source_is_refused(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    for params in ({"group": "nonsense"}, {"source": "carrier-pigeon"}):
        r = await client.get(_url(seed), params=params, headers=_owner(seed))
        assert r.status_code == 422


# ---- live -----------------------------------------------------------------------------------


async def test_a_new_phone_order_reaches_the_owner_live_and_a_reconnect_catches_up(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    voice_platform: FakeVoicePlatform,
    jobs: VoiceJobs,
    ws_url: str,  # noqa: F811
    owner_engine: AsyncEngine,
) -> None:
    await _turn_on(client, seed, jobs)
    token = seed.token(seed.owner_a, Role.OWNER)
    ws = await open_socket(ws_url, seed.outlet_a, token)
    await until_ready(ws)
    await _phone_order(client, voice_platform, env)
    pushed = await next_event(ws, "order_placed")
    assert pushed["payload"]["source"] == "voice"
    assert (await _orders(client, seed))["counts"]["new"] == 1  # the refetch it triggers

    # The screen drops its connection, another order arrives, and on reconnect it is replayed.
    await ws.close()
    await _phone_order(client, voice_platform, env, phone="+919999900808")
    ws2 = await open_socket(ws_url, seed.outlet_a, token, last_event_id=pushed["id"])
    replay = await until_ready(ws2)
    assert [m["event"] for m in replay if m["event"] == "order_placed"] == ["order_placed"]
    assert (await _orders(client, seed))["counts"]["new"] == 2
    await ws2.close()
    await asyncio.sleep(0)
    _ = hdr, owner_engine
