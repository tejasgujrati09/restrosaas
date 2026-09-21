"""Owner analytics. The dataset is seeded by hand with exact timestamps so every figure below
can be checked with arithmetic, and one test drives the real ordering endpoints to prove the
timestamps analytics reads are the ones the workflow writes."""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.v1 import analytics as analytics_api
from app.core.permissions import Role
from tests.api.guest_helpers import FakeClock, assign, kitchen, manager, new_guest, one, waiter
from tests.api.helpers import Menu
from tests.conftest import Seed, hdr

IST = timedelta(hours=5, minutes=30)


def ist(day: int, hh: int, mm: int = 0) -> datetime:
    """A September 2026 wall-clock time in India, as UTC."""
    return datetime(2026, 9, day, hh, mm, tzinfo=UTC) - IST


def base(seed: Seed) -> str:
    return f"/v1/outlets/{seed.outlet_a}/analytics"


@pytest.fixture(autouse=True)
async def reset_expected_prep(owner_engine: AsyncEngine, seed: Seed) -> AsyncIterator[None]:
    yield
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE outlet SET expected_prep_minutes = 10 WHERE id = :o"), {"o": seed.outlet_a}
        )
        await conn.execute(
            text("DELETE FROM audit_log WHERE restaurant_id = :r"), {"r": seed.restaurant_a}
        )


class Data:
    """Inserts tabs, rounds, lines and tickets straight into the database."""

    def __init__(self, engine: AsyncEngine, seed: Seed) -> None:
        self.engine, self.seed = engine, seed

    async def _table(self, label: str) -> uuid.UUID:
        async with self.engine.connect() as conn:
            found = await conn.scalar(
                text("SELECT id FROM dining_table WHERE outlet_id = :o AND label = :l"),
                {"o": self.seed.outlet_a, "l": label},
            )
        assert isinstance(found, uuid.UUID)
        return found

    async def tab(
        self, table: str, *, guests: int | None = None, closed: bool = False, opened: datetime
    ) -> uuid.UUID:
        tab_id = uuid.uuid4()
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tab (id, restaurant_id, outlet_id, table_id, status, opened_at, "
                    "closed_at, opened_by, guest_count) VALUES (:id, :r, :o, :t, :st, :at, :cl, "
                    "'customer', :g)"
                ),
                {
                    "id": tab_id,
                    "r": self.seed.restaurant_a,
                    "o": self.seed.outlet_a,
                    "t": await self._table(table),
                    "st": "closed" if closed else "open",
                    "at": opened,
                    "cl": opened + timedelta(hours=1) if closed else None,
                    "g": guests,
                },
            )
        return tab_id

    async def round(
        self,
        tab_id: uuid.UUID,
        seq: int,
        placed: datetime,
        status: str,
        lines: list[tuple[Any, int, int, str, datetime | None, uuid.UUID | None]],
        *,
        accepted: datetime | None = None,
        by_waiter: bool = False,
        ticket: tuple[str, datetime | None, datetime | None] | None = None,
    ) -> uuid.UUID:
        """`lines` are (menu item, qty, line total, status, served_at, served_by).
        `ticket` is (status, started_at, ready_at)."""
        order_id, ticket_id = uuid.uuid4(), uuid.uuid4()
        seed = self.seed
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tab_order (id, restaurant_id, outlet_id, tab_id, seq_no, status, "
                    "placed_at, placed_by_user_id, source, accepted_at) VALUES (:id, :r, :o, :tab, "
                    ":seq, :st, :at, :by, :src, :acc)"
                ),
                {
                    "id": order_id,
                    "r": seed.restaurant_a,
                    "o": seed.outlet_a,
                    "tab": tab_id,
                    "seq": seq,
                    "st": status,
                    "at": placed,
                    "by": seed.waiter_a if by_waiter else None,
                    "src": "waiter" if by_waiter else "customer",
                    "acc": accepted,
                },
            )
            if ticket is not None:
                await conn.execute(
                    text(
                        "INSERT INTO ticket (id, restaurant_id, outlet_id, order_id, tab_id, "
                        "status, created_at, started_at, ready_at) VALUES (:id, :r, :o, :ord, "
                        ":tab, :st, :at, :s, :rd)"
                    ),
                    {
                        "id": ticket_id,
                        "r": seed.restaurant_a,
                        "o": seed.outlet_a,
                        "ord": order_id,
                        "tab": tab_id,
                        "st": ticket[0],
                        "at": placed,
                        "s": ticket[1],
                        "rd": ticket[2],
                    },
                )
            for pos, (item, qty, total, lstatus, served_at, served_by) in enumerate(lines):
                await conn.execute(
                    text(
                        "INSERT INTO order_line (id, restaurant_id, order_id, tab_id, menu_item_id, "
                        "item_name_snapshot, qty, unit_price_snapshot, tax_class_snapshot, "
                        "line_total, status, placed_by, staff_user_id, ticket_id, position, "
                        "served_at, served_by) VALUES (:id, :r, :ord, :tab, :mi, :n, :q, :p, "
                        "'{}'::jsonb, :tot, :st, :pb, :su, :tk, :pos, :sa, :sb)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "r": seed.restaurant_a,
                        "ord": order_id,
                        "tab": tab_id,
                        "mi": uuid.UUID(item["id"]),
                        "n": item["name"],
                        "q": qty,
                        "p": total // qty,
                        "tot": total,
                        "st": lstatus,
                        "pb": "staff" if by_waiter else "customer",
                        "su": seed.waiter_a if by_waiter else None,
                        "tk": ticket_id if ticket is not None else None,
                        "pos": pos,
                        "sa": served_at,
                        "sb": served_by,
                    },
                )
        return order_id


async def add_item(
    env: Menu, client: httpx.AsyncClient, name: str, price: int, category: str
) -> Any:
    return (
        await client.post(
            f"{env.base}/items",
            json={
                "category_id": category,
                "name": name,
                "base_price_paise": price,
                "tax_class_id": env.tax_food["id"],
            },
            headers=env.owner,
        )
    ).json()


class World:
    def __init__(self, tikka: Any, dal: Any, naan: Any) -> None:
        self.tikka, self.dal, self.naan = tikka, dal, naan


@pytest.fixture
async def world(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    owner_engine: AsyncEngine,
    fake_clock: FakeClock,
) -> World:
    """Friday 18 Sep 2026, 19:00 in India is 'now'. Tikka costs 320, Dal 180, Naan 50.

    Today:  A  T1 12:00  Tikka x2 + Naan, ticket 12:02-12:14, served 12:17 by the waiter
            B  T2 13:00  Tikka, entered by the waiter, ticket 13:03-13:09, served 13:10 by the manager
            C  T1 13:20  Dal, cancelled by the guest
            D  T2 18:40  Dal x2, ticket started 18:45 and still cooking
    Yesterday: E  T1 13:00  Tikka, ticket 13:02-13:07, served 13:08
    """
    breads = (
        await client.post(f"{env.base}/categories", json={"name": "G Breads"}, headers=env.owner)
    ).json()
    tikka = env.item
    dal = await add_item(env, client, "G Dal", 18000, env.category["id"])
    naan = await add_item(env, client, "G Naan", 5000, breads["id"])
    d = Data(owner_engine, seed)
    wtr, mgr = seed.waiter_a, seed.manager_a

    t1 = await d.tab("T1", guests=4, opened=ist(18, 12))
    await d.round(
        t1, 1, ist(18, 12), "served",
        [(tikka, 2, 64000, "served", ist(18, 12, 17), wtr), (naan, 1, 5000, "served", ist(18, 12, 17), wtr)],
        accepted=ist(18, 12, 1), ticket=("bumped", ist(18, 12, 2), ist(18, 12, 14)),
    )  # fmt: skip
    await d.round(
        t1, 2, ist(18, 13, 20), "cancelled", [(dal, 1, 18000, "cancelled", None, None)],
        ticket=("cancelled", None, None),
    )  # fmt: skip
    t2 = await d.tab("T2", guests=2, opened=ist(18, 13))
    await d.round(
        t2, 1, ist(18, 13), "served", [(tikka, 1, 32000, "served", ist(18, 13, 10), mgr)],
        accepted=ist(18, 13, 1), by_waiter=True, ticket=("bumped", ist(18, 13, 3), ist(18, 13, 9)),
    )  # fmt: skip
    await d.round(
        t2, 2, ist(18, 18, 40), "preparing", [(dal, 2, 36000, "preparing", None, None)],
        accepted=ist(18, 18, 41), ticket=("preparing", ist(18, 18, 45), None),
    )  # fmt: skip
    old = await d.tab("T1", guests=3, closed=True, opened=ist(17, 13))
    await d.round(
        old, 1, ist(17, 13), "served", [(tikka, 1, 32000, "served", ist(17, 13, 8), wtr)],
        accepted=ist(17, 13, 1), ticket=("bumped", ist(17, 13, 2), ist(17, 13, 7)),
    )  # fmt: skip
    return World(tikka, dal, naan)


async def get(
    client: httpx.AsyncClient,
    seed: Seed,
    path: str,
    who: dict[str, str] | None = None,
    **params: Any,
) -> Any:
    r = await client.get(f"{base(seed)}/{path}", params=params, headers=who or manager(seed))
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- overview


async def test_overview_kpis_match_hand_computed_figures(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    body = await get(client, seed, "overview", **{"range": "today"})
    k = body["kpis"]
    assert body["range"]["start"] == body["range"]["end"] == "2026-09-18"
    assert (body["range"]["previous_start"], body["range"]["bucket"]) == ("2026-09-17", "day")

    # 3 live rounds (A, B, D); value 69000 + 32000 + 36000; yesterday 1 round of 32000.
    assert (k["orders"]["value"], k["orders"]["previous"], k["orders"]["change_pct"]) == (
        3,
        1,
        200.0,
    )
    assert (k["order_value"]["value"], k["order_value"]["previous"]) == (137000, 32000)
    assert k["order_value"]["change_pct"] == 328.1
    assert k["avg_order_value"]["value"] == 45667  # 137000 / 3, half up
    assert k["avg_order_value"]["change_pct"] == 42.7  # against 32000
    assert k["items_per_order"]["value"] == 2.0  # (3 + 1 + 2) units / 3 rounds

    # Prep: A 12 min, B 6 min. D has no ready time and C was cancelled: both left out.
    assert (k["avg_prep"]["value"], k["avg_prep"]["n"]) == (540.0, 2)
    assert (k["avg_prep"]["previous"], k["avg_prep"]["change_pct"]) == (300.0, 80.0)
    # Ready to served per item: A's two lines 180 s each, B's one 60 s.
    assert (k["avg_ready_to_served"]["value"], k["avg_ready_to_served"]["n"]) == (140.0, 3)
    # 4 rounds placed, 1 cancelled.
    assert (k["cancellation_rate"]["value"], k["cancellation_rate"]["n"]) == (25.0, 4)
    assert body["pending_orders"] == 1
    assert {(s["status"], s["n"]) for s in body["status_mix"]} == {
        ("served", 2),
        ("cancelled", 1),
        ("preparing", 1),
    }
    assert body["cancellations"]["rounds"] == 1
    assert body["cancellations"]["value_paise"] == 18000
    assert body["cancellations"]["items"] == [{"name": "G Dal", "units": 1, "value_paise": 18000}]


async def test_every_kpi_explains_itself(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    kpis = (await get(client, seed, "overview", **{"range": "today"}))["kpis"]
    for name, kpi in kpis.items():
        assert kpi["definition"] and kpi["basis"], name
    assert "not a bill" in kpis["order_value"]["definition"]
    assert "Cancelled tickets" in kpis["avg_prep"]["excluded"]


async def test_no_percent_change_without_a_valid_comparison(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    # Yesterday's previous period (the day before) has no rounds at all.
    k = (await get(client, seed, "overview", **{"range": "yesterday"}))["kpis"]
    assert k["orders"]["value"] == 1
    assert (k["orders"]["previous"], k["orders"]["change_pct"]) == (0, None)
    assert k["avg_prep"]["change_pct"] is None
    assert k["avg_order_value"]["previous"] is None


async def test_an_empty_range_has_no_values_rather_than_zeros_that_look_real(
    client: httpx.AsyncClient, seed: Seed, env: Menu, fake_clock: FakeClock
) -> None:
    body = await get(client, seed, "overview", **{"range": "today"})
    k = body["kpis"]
    assert (k["orders"]["value"], k["avg_order_value"]["value"], k["avg_prep"]["value"]) == (
        0,
        None,
        None,
    )
    assert k["cancellation_rate"]["value"] is None
    assert body["peak"]["windows"] == []
    assert [p["orders"] for p in body["trend"]] == [0]


async def test_the_day_is_the_outlets_day_not_utc(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    d = Data(owner_engine, seed)
    tab = await d.tab("T1", opened=ist(18, 0, 30))
    # 00:30 in India on the 18th is 19:00 UTC on the 17th.
    await d.round(tab, 1, ist(18, 0, 30), "placed", [(env.item, 1, 32000, "placed", None, None)])
    today = await get(client, seed, "overview", **{"range": "today"})
    yesterday = await get(client, seed, "overview", **{"range": "yesterday"})
    assert today["kpis"]["orders"]["value"] == 1
    assert yesterday["kpis"]["orders"]["value"] == 0
    hour_zero = today["peak"]["by_hour"][0]
    assert hour_zero["orders"] == 1


async def test_trend_fills_empty_days_and_peak_hours_use_local_time(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    body = await get(client, seed, "overview", **{"range": "last_7_days"})
    trend = {p["bucket"]: p for p in body["trend"]}
    assert len(trend) == 7
    assert trend["2026-09-18"]["orders"] == 3 and trend["2026-09-18"]["order_value_paise"] == 137000
    assert trend["2026-09-18"]["cancelled"] == 1
    assert trend["2026-09-17"]["orders"] == 1 and trend["2026-09-17"]["avg_prep_seconds"] == 300.0
    assert trend["2026-09-16"] == {
        "bucket": "2026-09-16", "orders": 0, "order_value_paise": 0, "cancelled": 0,
        "avg_prep_seconds": None, "prep_n": 0,
    }  # fmt: skip
    by_hour = {h["hour"]: h for h in body["peak"]["by_hour"]}
    assert [by_hour[h]["orders"] for h in (12, 13, 18)] == [
        1,
        2,
        1,
    ]  # Friday 12:00, 13:00 (B + E), 18:40
    assert by_hour[12]["lines_served"] == 2 and by_hour[13]["lines_served"] == 2
    assert by_hour[12]["tickets"] == 1
    # Peak hours are the ones within 75% of the busiest (13:00): only 13 itself.
    assert body["peak"]["windows"] == [{"start_hour": 13, "end_hour": 14}]
    assert body["peak"]["heatmap"][4][12] == 1  # Friday is row 4 (Monday = 0)
    assert body["peak"]["heatmap"][3][13] == 1  # yesterday, Thursday


async def test_a_longer_range_is_bucketed_by_week(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    body = await get(
        client, seed, "overview", **{"range": "custom", "from": "2026-08-01", "to": "2026-09-18"}
    )
    assert (body["range"]["days"], body["range"]["bucket"]) == (49, "week")
    assert body["trend"][0]["bucket"] == "2026-07-27"  # weeks start on Monday
    assert sum(p["orders"] for p in body["trend"]) == 4  # A, B, D and yesterday's E


# --------------------------------------------------------------------------- kitchen


async def test_kitchen_timings_and_what_was_left_out(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    body = await get(client, seed, "kitchen", **{"range": "today"})
    k = body["kpis"]
    assert k["avg_prep"]["value"] == 540.0
    assert k["avg_wait"]["value"] == 90.0  # A waited 60 s after acceptance, B 120 s
    assert k["avg_to_ready"]["value"] == 690.0  # placed to ready: A 14 min, B 9 min
    assert (k["over_expected"]["value"], k["over_expected"]["n"]) == (
        50.0,
        2,
    )  # only A took over 10 min
    assert body["coverage"] == {
        "total": 4,
        "used": 2,
        "cancelled": 1,
        "unfinished": 1,
        "invalid": 0,
    }
    assert body["expected_prep_minutes"] == 10
    assert [(p["n"], p["avg_prep_seconds"]) for p in body["by_hour"] if p["n"]] == [
        (1, 720.0),
        (1, 360.0),
    ]


async def test_delays_follow_the_expected_prep_time(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    r = await client.put(f"{base(seed)}/expected-prep", json={"minutes": 15}, headers=manager(seed))
    assert (r.status_code, r.json()) == (200, {"expected_prep_minutes": 15})
    body = await get(client, seed, "kitchen", **{"range": "today"})
    assert body["kpis"]["over_expected"]["value"] == 0.0  # 12 min is now within 15
    # D has been cooking since 18:45, 15 minutes at 19:00: not yet *over* 15.
    assert body["live"]["preparing"] == {"n": 1, "over_expected": 0, "longest_seconds": 900}
    await client.put(f"{base(seed)}/expected-prep", json={"minutes": 10}, headers=manager(seed))
    live = (await get(client, seed, "kitchen", **{"range": "today"}))["live"]
    assert live["preparing"]["over_expected"] == 1


async def test_items_with_too_few_tickets_are_not_ranked_slow_or_fast(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    body = await get(client, seed, "kitchen", **{"range": "today"})
    assert body["slowest"] == [] and body["fastest"] == []
    assert body["items_hidden_low_sample"] == 2  # Tikka (2 tickets) and Naan (1)
    cats = {c["name"]: c for c in body["by_category"]}
    assert cats["G Starters"]["avg_prep_seconds"] == 540.0 and cats["G Starters"]["n"] == 2
    assert cats["G Breads"]["avg_prep_seconds"] == 720.0 and cats["G Breads"]["low_sample"] is True


async def test_enough_tickets_rank_items_with_their_numbers(
    client: httpx.AsyncClient, seed: Seed, world: World, owner_engine: AsyncEngine
) -> None:
    d = Data(owner_engine, seed)
    tab = await d.tab("T1", closed=True, opened=ist(16, 12))
    for i, prep in enumerate((100, 200, 300)):
        start = ist(16, 12, i * 10)
        await d.round(
            tab, i + 1, start, "served", [(world.dal, 1, 18000, "served", None, None)],
            accepted=start, ticket=("bumped", start, start + timedelta(seconds=prep)),
        )  # fmt: skip
    body = await get(client, seed, "kitchen", **{"range": "last_7_days"})
    # Tikka's tickets in the week are A (720 s), B (360 s) and E (300 s); Dal's are the three seeded here.
    assert [(i["name"], i["n"], i["avg_prep_seconds"]) for i in body["slowest"]] == [
        ("G Paneer Tikka", 3, 460.0),
        ("G Dal", 3, 200.0),
    ]
    assert [i["name"] for i in body["fastest"]] == ["G Dal", "G Paneer Tikka"]


async def test_tickets_with_missing_or_reversed_timestamps_are_excluded_and_counted(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    d = Data(owner_engine, seed)
    tab = await d.tab("T1", opened=ist(18, 10))
    line = [(env.item, 1, 32000, "served", None, None)]
    await d.round(tab, 1, ist(18, 10), "served", line, accepted=ist(18, 10), ticket=("bumped", ist(18, 10, 1), ist(18, 10, 5)))  # fmt: skip
    await d.round(tab, 2, ist(18, 11), "served", line, accepted=ist(18, 11), ticket=("bumped", ist(18, 11, 9), ist(18, 11, 5)))  # fmt: skip
    await d.round(tab, 3, ist(18, 12), "served", line, accepted=ist(18, 12), ticket=("bumped", None, ist(18, 12, 5)))  # fmt: skip
    body = await get(client, seed, "kitchen", **{"range": "today"})
    assert body["coverage"] == {
        "total": 3,
        "used": 1,
        "cancelled": 0,
        "unfinished": 1,
        "invalid": 1,
    }
    assert body["kpis"]["avg_prep"]["value"] == 240.0


async def test_live_buckets_count_waiting_cooking_and_ready_orders(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    d = Data(owner_engine, seed)
    tab = await d.tab("T1", opened=ist(18, 18))
    line = [(env.item, 1, 32000, "placed", None, None)]
    await d.round(tab, 1, ist(18, 18, 54), "accepted", line, accepted=ist(18, 18, 55), ticket=("queued", None, None))  # fmt: skip
    await d.round(tab, 2, ist(18, 18, 20), "accepted", line, accepted=ist(18, 18, 21), ticket=("queued", None, None))  # fmt: skip
    await d.round(
        tab, 3, ist(18, 18, 50), "placed", line, ticket=("queued", None, None)
    )  # still in the undo window
    await d.round(tab, 4, ist(18, 18, 0), "ready", line, accepted=ist(18, 18, 1), ticket=("ready", ist(18, 18, 2), ist(18, 18, 30)))  # fmt: skip
    live = (await get(client, seed, "kitchen", **{"range": "today"}))["live"]
    assert live["waiting_for_kitchen"] == {"n": 2, "over_expected": 1, "longest_seconds": 39 * 60}
    assert live["preparing"]["n"] == 0
    # Ready orders are counted, never judged late: nothing defines how long they may wait.
    assert live["ready_awaiting_serve"] == {"n": 1, "over_expected": 0, "longest_seconds": 30 * 60}


# --------------------------------------------------------------------------- staff


async def test_staff_metrics_credit_whoever_served(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    body = await get(client, seed, "staff", **{"range": "today"})
    rows = {r["user_id"]: r for r in body["rows"]}
    w = rows[str(seed.waiter_a)]
    assert (w["lines_served"], w["units_served"], w["rounds_served"], w["tables_served"]) == (
        2,
        3,
        1,
        1,
    )
    assert (
        w["order_value_served_paise"],
        w["avg_ready_to_served_seconds"],
        w["ready_to_served_n"],
    ) == (69000, 180.0, 2)
    assert (w["active_days"], w["lines_per_active_day"], w["peak_hour"]) == (1, 2.0, 12)
    assert (w["rounds_entered"], w["order_value_entered_paise"]) == (
        1,
        32000,
    )  # B was typed in by the waiter
    m = rows[str(seed.manager_a)]
    assert (m["lines_served"], m["tables_served"], m["avg_ready_to_served_seconds"]) == (1, 1, 60.0)
    assert (m["rounds_entered"], m["role"]) == (0, "manager")
    assert [h["lines_served"] for h in body["by_hour"] if h["lines_served"]] == [2, 1]
    assert body["can_export"] is False  # a manager sees the numbers but not the export
    assert body["by_hour"][12]["staff_active"] == 1
    assert body["by_hour"][13]["lines_per_staff"] == 1.0
    assert not any("cancel" in k for k in w), "cancellations are never attributed to a waiter"
    assert any("not attributed" in n for n in body["notes"])


async def test_no_phone_numbers_in_any_response(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    for path in ("overview", "kitchen", "staff", "menu", "tables", "orders"):
        text_ = (await client.get(f"{base(seed)}/{path}", headers=manager(seed))).text
        assert seed.phones["waiter_a"] not in text_ and "phone" not in text_


# --------------------------------------------------------------------------- menu and tables


async def test_menu_separates_most_ordered_from_highest_value(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    body = await get(client, seed, "menu", **{"range": "today"})
    items = {i["name"]: i for i in body["items"]}
    assert (body["total_units"], body["total_order_value_paise"]) == (6, 137000)
    tikka, dal, naan = items["G Paneer Tikka"], items["G Dal"], items["G Naan"]
    assert (tikka["units"], tikka["rounds"], tikka["order_value_paise"]) == (3, 2, 96000)
    assert (tikka["share_pct"], tikka["avg_price_paise"]) == (70.1, 32000)
    assert (dal["units"], dal["order_value_paise"], dal["dropped_units"]) == (2, 36000, 1)
    assert dal["dropped_rate_pct"] == 33.3  # 1 of the 3 ordered was cancelled
    assert (naan["units"], naan["order_value_paise"]) == (1, 5000)
    # Both orderings are derivable from the payload: by units, Tikka then Dal; by value, the same here.
    assert [i["name"] for i in sorted(body["items"], key=lambda i: -i["units"])][:2] == [
        "G Paneer Tikka",
        "G Dal",
    ]
    assert tikka["avg_prep_seconds"] == 540.0 and tikka["prep_n"] == 2
    assert (
        dal["avg_prep_seconds"] is None
    )  # its only live ticket is unfinished: no timing, not a zero
    # Neutral position labels against the medians (units 2, value 36000).
    assert tikka["quadrant"] == "high_volume_high_value"
    assert naan["quadrant"] == "low_volume_low_value"
    assert (body["median_units"], body["median_order_value_paise"]) == (2.0, 36000.0)
    cats = {c["name"]: c for c in body["categories"]}
    assert (cats["G Starters"]["rounds"], cats["G Starters"]["order_value_paise"]) == (3, 132000)
    assert cats["G Starters"]["avg_order_value_paise"] == 44000
    assert (cats["G Breads"]["units"], cats["G Breads"]["avg_order_value_paise"]) == (1, 5000)


async def test_table_revenue_visits_and_guests(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    body = await get(client, seed, "tables", **{"range": "today"})
    rows = {r["label"]: r for r in body["rows"]}
    assert (
        rows["T1"]["visits"],
        rows["T1"]["rounds"],
        rows["T1"]["order_value_paise"],
        rows["T1"]["guests"],
    ) == (1, 1, 69000, 4)
    assert (
        rows["T2"]["visits"],
        rows["T2"]["rounds"],
        rows["T2"]["order_value_paise"],
        rows["T2"]["guests"],
    ) == (1, 2, 68000, 2)
    assert rows["T2"]["avg_round_value_paise"] == 34000
    assert any("turnaround" in n for n in body["notes"])
    assert body["rows"][0]["label"] == "T1"  # highest order value first


# --------------------------------------------------------------------------- drill-down


async def orders_for(client: httpx.AsyncClient, seed: Seed, **params: Any) -> dict[str, Any]:
    params.setdefault("range", "today")
    return dict(await get(client, seed, "orders", **params))


async def test_drill_down_lists_the_rounds_behind_a_number(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    everything = await orders_for(client, seed)
    assert [(r["table_label"], r["seq_no"], r["status"]) for r in everything["rows"]] == [
        ("T2", 2, "preparing"), ("T1", 2, "cancelled"), ("T2", 1, "served"), ("T1", 1, "served"),
    ]  # fmt: skip
    top = everything["rows"][3]
    assert top["order_value_paise"] == 69000 and top["items"] == "2 × G Paneer Tikka, 1 × G Naan"
    assert (top["prep_seconds"], top["delayed"]) == (720.0, True)

    by_item = await orders_for(client, seed, item_id=world.tikka["id"])
    assert [r["table_label"] for r in by_item["rows"]] == ["T2", "T1"]
    assert [r["seq_no"] for r in (await orders_for(client, seed, delayed="true"))["rows"]] == [1]
    only_manager = await orders_for(client, seed, served_by=str(seed.manager_a))
    assert [(r["table_label"], r["served_by"]) for r in only_manager["rows"]] == [("T2", "Unnamed")]
    assert len((await orders_for(client, seed, hour=13))["rows"]) == 2  # B and the cancelled C
    assert len((await orders_for(client, seed, status="cancelled"))["rows"]) == 1
    assert len((await orders_for(client, seed, weekday=5, day="2026-09-18"))["rows"]) == 4
    assert (await orders_for(client, seed, weekday=4))["rows"] == []
    assert len((await orders_for(client, seed, category_id=world.naan["category_id"]))["rows"]) == 1


async def test_drill_down_pages_with_a_stable_cursor(
    client: httpx.AsyncClient, seed: Seed, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(analytics_api, "_ORDER_PAGE", 3)
    first = await orders_for(client, seed)
    assert len(first["rows"]) == 3 and first["next_cursor"]
    second = await orders_for(client, seed, cursor=first["next_cursor"])
    assert len(second["rows"]) == 1 and second["next_cursor"] is None
    seen = [r["id"] for r in first["rows"] + second["rows"]]
    assert len(set(seen)) == 4
    bad = await client.get(
        f"{base(seed)}/orders", params={"cursor": "nonsense"}, headers=manager(seed)
    )
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_cursor")


# --------------------------------------------------------------------------- access


async def test_only_owner_and_manager_see_analytics(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    for path in ("overview", "kitchen", "staff", "menu", "tables", "orders"):
        for who in (waiter(seed), kitchen(seed)):
            r = await client.get(f"{base(seed)}/{path}", headers=who)
            assert r.status_code == 403, (path, r.text)
        for ok in (manager(seed), hdr(seed.token(seed.owner_a, Role.OWNER))):
            assert (await client.get(f"{base(seed)}/{path}", headers=ok)).status_code == 200
    assert (await client.get(f"{base(seed)}/overview")).status_code == 401


async def test_another_restaurants_owner_cannot_read_or_see_this_data(
    client: httpx.AsyncClient, seed: Seed, world: World
) -> None:
    theirs = hdr(seed.token(seed.owner_b, Role.OWNER, tenant="b"))
    forbidden = await client.get(f"{base(seed)}/overview", headers=theirs)
    assert forbidden.status_code == 403
    own = await client.get(
        f"/v1/outlets/{seed.outlet_b}/analytics/overview", params={"range": "today"}, headers=theirs
    )
    assert own.status_code == 200
    k = own.json()["kpis"]
    assert (k["orders"]["value"], k["order_value"]["value"], k["avg_prep"]["value"]) == (0, 0, None)


async def test_bad_ranges_are_refused_with_a_reason(
    client: httpx.AsyncClient, seed: Seed, env: Menu, fake_clock: FakeClock
) -> None:
    for params, fragment in (
        ({"range": "custom"}, "Choose a start"),
        ({"range": "custom", "from": "2026-09-19", "to": "2026-09-19"}, "future"),
        ({"range": "custom", "from": "2026-09-10", "to": "2026-09-01"}, "on or before"),
        ({"range": "custom", "from": "2024-01-01", "to": "2026-09-18"}, "at most 366"),
    ):
        r = await client.get(f"{base(seed)}/overview", params=params, headers=manager(seed))
        assert (r.status_code, r.json()["code"]) == (422, "invalid_range")
        assert fragment in r.json()["message"]
    ok = await client.get(
        f"{base(seed)}/overview",
        params={"range": "custom", "from": "2026-09-01", "to": "2026-09-10"},
        headers=manager(seed),
    )
    assert ok.status_code == 200 and ok.json()["range"]["days"] == 10


# --------------------------------------------------------------------------- expected prep time


async def test_owner_and_manager_can_set_the_expected_prep_time_and_it_is_audited(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    owner = hdr(seed.token(seed.owner_a, Role.OWNER))
    assert (await get(client, seed, "kitchen", **{"range": "today"}))["expected_prep_minutes"] == 10
    for who, minutes in ((manager(seed), 12), (owner, 8)):
        r = await client.put(f"{base(seed)}/expected-prep", json={"minutes": minutes}, headers=who)
        assert (r.status_code, r.json()["expected_prep_minutes"]) == (200, minutes)
    body = await get(client, seed, "overview", who=owner, **{"range": "today"})
    assert (body["expected_prep_minutes"], body["can_edit_expected_prep"], body["can_export"]) == (
        8,
        True,
        True,
    )
    assert (await get(client, seed, "overview", **{"range": "today"}))["can_export"] is False
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT before, after FROM audit_log WHERE restaurant_id = :r AND action = :a ORDER BY at"
                ),
                {"r": seed.restaurant_a, "a": "outlet.expected_prep_minutes.update"},
            )
        ).all()
    assert [(b["expected_prep_minutes"], a["expected_prep_minutes"]) for b, a in rows] == [
        (10, 12),
        (12, 8),
    ]


async def test_waiters_and_kitchen_cannot_change_it_and_bad_values_are_refused(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    for who in (waiter(seed), kitchen(seed)):
        r = await client.put(f"{base(seed)}/expected-prep", json={"minutes": 5}, headers=who)
        assert r.status_code == 403
    for bad in (0, 241, -3):
        r = await client.put(
            f"{base(seed)}/expected-prep", json={"minutes": bad}, headers=manager(seed)
        )
        assert r.status_code == 422
    other = hdr(seed.token(seed.owner_b, Role.OWNER, tenant="b"))
    assert (
        await client.put(f"{base(seed)}/expected-prep", json={"minutes": 5}, headers=other)
    ).status_code == 403


async def test_a_replayed_change_returns_the_original_answer(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    key = uuid.uuid4()
    headers = {**manager(seed), "Idempotency-Key": str(key)}
    first = await client.put(f"{base(seed)}/expected-prep", json={"minutes": 20}, headers=headers)
    again = await client.put(f"{base(seed)}/expected-prep", json={"minutes": 20}, headers=headers)
    assert first.json() == again.json() == {"expected_prep_minutes": 20}


# --------------------------------------------------------------------------- export


async def test_only_the_owner_can_export_and_names_cannot_run_as_formulas(
    client: httpx.AsyncClient, seed: Seed, world: World, owner_engine: AsyncEngine
) -> None:
    owner = hdr(seed.token(seed.owner_a, Role.OWNER))
    denied = await client.get(
        f"{base(seed)}/export/orders", params={"range": "today"}, headers=manager(seed)
    )
    assert denied.status_code == 403
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE menu_item SET name = '=HYPERLINK(\"x\")' WHERE id = :i"),
            {"i": uuid.UUID(world.naan["id"])},
        )
    r = await client.get(f"{base(seed)}/export/menu", params={"range": "today"}, headers=owner)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:5] == ["Item", "Category", "Rounds", "Units", "Order value (INR)"]
    assert '\'=HYPERLINK("x")' in [row[0] for row in rows]
    tikka = next(row for row in rows if row[0] == "G Paneer Tikka")
    assert tikka[4] == "960.00"  # plain rupees a spreadsheet can total

    orders = list(
        csv.reader(
            io.StringIO(
                (
                    await client.get(
                        f"{base(seed)}/export/orders", params={"range": "today"}, headers=owner
                    )
                ).text
            )
        )
    )
    assert len(orders) == 5  # header + 4 rounds
    assert orders[4][0] == "2026-09-18 12:00" and orders[4][6] == "690.00"
    staff_rows = list(
        csv.reader(
            io.StringIO(
                (
                    await client.get(
                        f"{base(seed)}/export/staff", params={"range": "today"}, headers=owner
                    )
                ).text
            )
        )
    )
    assert len(staff_rows) == 3
    assert not any(seed.phones["waiter_a"] in c for row in staff_rows for c in row)


# --------------------------------------------------------------------------- the real workflow


async def test_analytics_reads_what_the_real_workflow_writes(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    """Order -> undo window closes -> kitchen starts -> ready -> waiter serves, through the API."""
    await assign(owner_engine, seed, "T1")
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item, 2)])).json()
    fake_clock.advance(61)
    tickets = (
        await client.get(f"/v1/outlets/{seed.outlet_a}/tickets", headers=kitchen(seed))
    ).json()["queue"]
    tid = tickets[0]["id"]
    fake_clock.advance(120)  # waits 2 minutes before the kitchen starts it
    await client.post(f"/v1/outlets/{seed.outlet_a}/tickets/{tid}/start", headers=kitchen(seed))
    fake_clock.advance(420)  # 7 minutes of cooking
    await client.post(f"/v1/outlets/{seed.outlet_a}/tickets/{tid}/ready", headers=kitchen(seed))
    fake_clock.advance(90)  # ready for a minute and a half
    served = await client.post(
        f"/v1/outlets/{seed.outlet_a}/staff/tabs/{g.tab_id}/orders/{placed['id']}/serve",
        json={},
        headers=waiter(seed),
    )
    assert served.status_code == 200, served.text

    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT served_at, served_by FROM order_line WHERE order_id = :o"),
                {"o": uuid.UUID(placed["id"])},
            )
        ).one()
    assert row.served_by == seed.waiter_a and row.served_at == fake_clock.now

    overview = await get(client, seed, "overview", **{"range": "today"})
    k = overview["kpis"]
    assert (k["orders"]["value"], k["order_value"]["value"]) == (1, 64000)
    assert (k["avg_prep"]["value"], k["avg_ready_to_served"]["value"]) == (420.0, 90.0)
    kitchen_body = await get(client, seed, "kitchen", **{"range": "today"})
    async with owner_engine.connect() as conn:
        accepted = await conn.scalar(
            text("SELECT accepted_at FROM tab_order WHERE id = :o"), {"o": uuid.UUID(placed["id"])}
        )
        started = await conn.scalar(
            text("SELECT started_at FROM ticket WHERE id = :t"), {"t": uuid.UUID(tid)}
        )
    assert kitchen_body["kpis"]["avg_wait"]["value"] == (started - accepted).total_seconds()
    assert kitchen_body["kpis"]["avg_to_ready"]["value"] == 61 + 120 + 420  # placed to ready
    staff_body = await get(client, seed, "staff", **{"range": "today"})
    mine = next(r for r in staff_body["rows"] if r["user_id"] == str(seed.waiter_a))
    assert (mine["lines_served"], mine["units_served"], mine["tables_served"]) == (1, 2, 1)
    assert mine["avg_ready_to_served_seconds"] == 90.0
