"""Guest side of a tab: QR landing, menu, placing and undoing rounds, the live
tab, service charge and service requests. Time is controlled through
`app.clock` so the 60-second window and happy-hour boundaries are exact."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app import clock
from app.core.permissions import Role
from app.db.session import qr_session, tenant_session
from tests.api.helpers import Menu, build_menu, cleanup_menu
from tests.conftest import Seed, hdr

# Friday 19:00 in Asia/Kolkata (13:30 UTC).
FRIDAY_7PM_IST = datetime(2026, 9, 18, 13, 30, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock(FRIDAY_7PM_IST)
    monkeypatch.setattr(clock, "utcnow", lambda: fake.now)
    return fake


async def _wipe_tabs(owner_engine: AsyncEngine, seed: Seed) -> None:
    async with owner_engine.begin() as conn:
        for table in (
            "tab_event",
            "service_request",
            "order_line",
            "tab_order",
            "tab_session",
            "tab",
        ):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE restaurant_id = :r"), {"r": seed.restaurant_a}
            )
        await conn.execute(
            text(
                "UPDATE outlet SET waiter_confirm_mode = false, liquor_licensed = false, "
                "liquor_approval_required = false, service_charge_bp = 0, "
                "liquor_vat_rate_bp = 0 WHERE id = :o"
            ),
            {"o": seed.outlet_a},
        )
        await conn.execute(
            text("UPDATE dining_table SET requires_waiter_confirm = false, active = true"),
        )


@pytest.fixture
async def env(
    client: httpx.AsyncClient, seed: Seed, owner_engine: AsyncEngine
) -> AsyncIterator[Menu]:
    await _wipe_tabs(owner_engine, seed)
    menu = await build_menu(client, seed, "G")
    yield menu
    await _wipe_tabs(owner_engine, seed)
    await cleanup_menu(client, menu)


def owner(seed: Seed) -> dict[str, str]:
    return hdr(seed.token(seed.owner_a, Role.OWNER))


async def table_token(client: httpx.AsyncClient, seed: Seed, label: str = "T1") -> str:
    tables = (await client.get(f"/v1/outlets/{seed.outlet_a}/tables", headers=owner(seed))).json()
    url = next(t["qr_url"] for t in tables if t["label"] == label)
    return str(url.rsplit("/", 1)[1])


async def scan(
    client: httpx.AsyncClient, qr_token: str, session_token: str | None = None
) -> httpx.Response:
    headers = hdr(session_token) if session_token else {}
    return await client.post(f"/v1/qr/{qr_token}/session", json={}, headers=headers)


class Guest:
    def __init__(self, client: httpx.AsyncClient, seed: Seed, scan_body: dict[str, Any]) -> None:
        self.client = client
        self.seed = seed
        self.token: str = scan_body["session_token"]
        self.tab_id: str = scan_body["tab_id"]
        self.outlet_id: str = scan_body["outlet_id"]
        self.base = f"/v1/outlets/{self.outlet_id}/tabs/{self.tab_id}"

    def headers(self, key: uuid.UUID | None = None) -> dict[str, str]:
        return hdr(self.token, key)

    async def menu(self) -> dict[str, Any]:
        r = await self.client.get(
            f"/v1/outlets/{self.outlet_id}/guest/menu", headers=self.headers()
        )
        assert r.status_code == 200, r.text
        return dict(r.json())

    async def order(
        self, lines: list[dict[str, Any]], key: uuid.UUID | None = None
    ) -> httpx.Response:
        return await self.client.post(
            f"{self.base}/orders", json={"lines": lines}, headers=self.headers(key)
        )

    async def tab(self) -> dict[str, Any]:
        r = await self.client.get(self.base, headers=self.headers())
        assert r.status_code == 200, r.text
        return dict(r.json())


async def new_guest(client: httpx.AsyncClient, seed: Seed, label: str = "T1") -> Guest:
    r = await scan(client, await table_token(client, seed, label))
    assert r.status_code == 200, r.text
    return Guest(client, seed, r.json())


def one(item: dict[str, Any], qty: int = 1, **extra: Any) -> dict[str, Any]:
    return {"menu_item_id": item["id"], "qty": qty, **extra}


async def events(owner_engine: AsyncEngine, tab_id: str) -> list[tuple[str, str]]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT event, actor_type FROM tab_event WHERE tab_id = :t ORDER BY id"),
            {"t": uuid.UUID(tab_id)},
        )
        return [(r[0], r[1]) for r in rows]


# --- QR landing ---------------------------------------------------------------


async def test_scan_opens_a_tab_and_returns_a_session(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    r = await scan(client, await table_token(client, seed))
    body = r.json()
    assert r.status_code == 200
    assert body["table_label"] == "T1" and body["tab_status"] == "open"
    assert body["awaiting_waiter"] is False
    assert body["session_token"].startswith(seed.restaurant_a.hex + ".")
    assert await events(owner_engine, body["tab_id"]) == [("opened", "customer")]


async def test_second_phone_joins_the_same_tab_with_its_own_session(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    token = await table_token(client, seed)
    first = (await scan(client, token)).json()
    second = (await scan(client, token)).json()
    assert first["tab_id"] == second["tab_id"]
    assert first["session_token"] != second["session_token"]


async def test_rescanning_with_a_live_session_reuses_it(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    token = await table_token(client, seed)
    first = (await scan(client, token)).json()
    again = (await scan(client, token, first["session_token"])).json()
    assert again["session_token"] is None
    assert again["tab_id"] == first["tab_id"] and again["expires_at"] == first["expires_at"]


async def test_concurrent_first_scans_open_exactly_one_tab(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    token = await table_token(client, seed, "T2")
    results = await asyncio.gather(*(scan(client, token) for _ in range(6)))
    assert {r.status_code for r in results} == {200}
    assert len({r.json()["tab_id"] for r in results}) == 1
    async with owner_engine.connect() as conn:
        count = await conn.scalar(
            text("SELECT count(*) FROM tab WHERE restaurant_id = :r AND status = 'open'"),
            {"r": seed.restaurant_a},
        )
    assert count == 1


async def test_repeated_scans_keep_hitting_the_partial_unique_index(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    """Regression: the ON CONFLICT target only matched the partial index while the
    statement was on a custom plan, so the sixth scan of a table used to fail."""
    token = await table_token(client, seed)
    tab_ids = {(await scan(client, token)).json()["tab_id"] for _ in range(12)}
    assert len(tab_ids) == 1


async def test_unknown_rotated_and_inactive_qr_codes_are_refused(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    assert (await scan(client, "nope")).status_code == 404
    assert (await scan(client, "x" * 65)).json()["code"] == "qr_not_found"
    tables = (await client.get(f"/v1/outlets/{seed.outlet_a}/tables", headers=owner(seed))).json()
    t2 = next(t for t in tables if t["label"] == "T2")
    old = t2["qr_url"].rsplit("/", 1)[1]
    assert (await scan(client, old)).status_code == 200
    await client.post(
        f"/v1/outlets/{seed.outlet_a}/tables/{t2['id']}/rotate-qr", headers=owner(seed)
    )
    assert (await scan(client, old)).json()["code"] == "qr_not_found"
    await client.put(
        f"/v1/outlets/{seed.outlet_a}/tables/{t2['id']}",
        json={"label": "T2", "active": False},
        headers=owner(seed),
    )
    new = (await client.get(f"/v1/outlets/{seed.outlet_a}/tables", headers=owner(seed))).json()
    inactive = next(t for t in new if t["label"] == "T2")["qr_url"].rsplit("/", 1)[1]
    assert (await scan(client, inactive)).status_code == 404


async def test_suspended_restaurant_takes_no_orders(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    token = await table_token(client, seed)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE restaurant SET status = 'suspended' WHERE id = :r"),
            {"r": seed.restaurant_a},
        )
    try:
        r = await scan(client, token)
        assert (r.status_code, r.json()["code"]) == (403, "outlet_unavailable")
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE restaurant SET status = 'active' WHERE id = :r"),
                {"r": seed.restaurant_a},
            )


async def test_qr_lookup_policy_exposes_only_the_held_token(seed: Seed) -> None:
    """RLS: with a QR token set, exactly one table row is visible, across tenants."""
    from sqlalchemy import select

    from app.domains.tenant.models import DiningTable

    async with tenant_session(seed.restaurant_a) as session:
        token_a = await session.scalar(
            select(DiningTable.qr_token).where(DiningTable.label == "T1")
        )
    assert token_a is not None
    async with qr_session(token_a) as session:
        visible = (await session.scalars(select(DiningTable))).all()
    assert [t.label for t in visible] == ["T1"]
    async with qr_session("not-a-token") as session:
        assert (await session.scalars(select(DiningTable))).all() == []
    async with qr_session("") as session:
        assert (await session.scalars(select(DiningTable))).all() == []


# --- session checks -----------------------------------------------------------


async def test_requests_without_a_valid_session_are_refused(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    assert (await client.get(g.base)).json()["code"] == "not_authenticated"
    for bad in ("garbage", "a" * 32 + ".secret", seed.restaurant_a.hex + ".wrong"):
        r = await client.get(g.base, headers=hdr(bad))
        assert r.status_code == 401, bad
    staff_jwt = seed.token(seed.owner_a, Role.OWNER)
    assert (await client.get(g.base, headers=hdr(staff_jwt))).status_code == 401


async def test_session_for_tab_a_cannot_touch_tab_b(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    a = await new_guest(client, seed, "T1")
    b = await new_guest(client, seed, "T2")
    item = env.item
    cross = f"/v1/outlets/{a.outlet_id}/tabs/{b.tab_id}"
    r = await client.post(f"{cross}/orders", json={"lines": [one(item)]}, headers=a.headers())
    assert (r.status_code, r.json()["code"]) == (403, "permission_denied")
    assert (await client.get(cross, headers=a.headers())).status_code == 403
    assert (
        await client.put(f"{cross}/service-charge", json={"removed": True}, headers=a.headers())
    ).status_code == 403
    assert (
        await client.post(f"{cross}/service-requests", json={"type": "waiter"}, headers=a.headers())
    ).status_code == 403
    assert (await b.tab())["rounds"] == []


async def test_session_cannot_be_used_on_another_outlet(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    r = await client.get(f"/v1/outlets/{seed.outlet_b}/tabs/{g.tab_id}", headers=g.headers())
    assert r.status_code == 403
    r = await client.get(f"/v1/outlets/{seed.outlet_b}/guest/menu", headers=g.headers())
    assert r.status_code == 403


async def test_another_restaurants_tab_id_is_invisible(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    """A token whose prefix names restaurant B, with restaurant A's secret, finds nothing."""
    g = await new_guest(client, seed)
    _, secret = g.token.split(".", 1)
    forged = f"{seed.restaurant_b.hex}.{secret}"
    r = await client.get(g.base, headers=hdr(forged))
    assert r.status_code == 401


async def test_session_expires_after_six_hours(
    client: httpx.AsyncClient, seed: Seed, env: Menu, fake_clock: FakeClock
) -> None:
    g = await new_guest(client, seed)
    fake_clock.advance(6 * 3600 - 1)
    assert (await client.get(g.base, headers=g.headers())).status_code == 200
    fake_clock.advance(2)
    r = await client.get(g.base, headers=g.headers())
    assert (r.status_code, r.json()["code"]) == (401, "session_ended")


async def test_session_ends_when_the_tab_closes(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    g = await new_guest(client, seed)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE tab SET status = 'closed', closed_at = now() WHERE id = :t"),
            {"t": uuid.UUID(g.tab_id)},
        )
    r = await client.get(g.base, headers=g.headers())
    assert (r.status_code, r.json()["code"]) == (401, "session_ended")
    # A fresh scan starts a new tab on the same table.
    again = await scan(client, await table_token(client, seed))
    assert again.json()["tab_id"] != g.tab_id


async def test_one_live_tab_per_table_is_enforced_by_the_database(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    g = await new_guest(client, seed)
    async with owner_engine.begin() as conn:
        table_id = await conn.scalar(
            text("SELECT table_id FROM tab WHERE id = :t"), {"t": uuid.UUID(g.tab_id)}
        )
    for status in ("open", "bill_requested"):
        with pytest.raises(DBAPIError):
            async with owner_engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO tab (id, restaurant_id, outlet_id, table_id, status, "
                        "opened_by) VALUES (:i, :r, :o, :t, :s, 'waiter')"
                    ),
                    {
                        "i": uuid.uuid4(),
                        "r": seed.restaurant_a,
                        "o": seed.outlet_a,
                        "t": table_id,
                        "s": status,
                    },
                )


# --- menu ---------------------------------------------------------------------


async def test_guest_menu_shows_available_items_at_todays_price(
    client: httpx.AsyncClient, seed: Seed, env: Menu, fake_clock: FakeClock
) -> None:
    g = await new_guest(client, seed)
    menu = await g.menu()
    assert menu["prices_include_tax"] is True
    category = next(c for c in menu["categories"] if c["name"] == "G Starters")
    item = category["items"][0]
    assert (item["name"], item["price_paise"], item["price_rule"]) == (
        "G Paneer Tikka",
        32000,
        None,
    )
    assert item["available"] is True and item["self_orderable"] is True


async def test_sold_out_hidden_and_windowed_categories(
    client: httpx.AsyncClient, seed: Seed, env: Menu, fake_clock: FakeClock
) -> None:
    off = await client.put(
        f"{env.base}/items/{env.item['id']}/availability",
        json={"available": False},
        headers=owner(seed),
    )
    assert off.status_code == 200
    breakfast = (
        await client.post(
            f"{env.base}/categories",
            json={"name": "G Breakfast", "available_from": "06:00:00", "available_to": "11:00:00"},
            headers=owner(seed),
        )
    ).json()
    hidden = (
        await client.post(
            f"{env.base}/categories",
            json={"name": "G Hidden", "visible": False},
            headers=owner(seed),
        )
    ).json()
    for cat in (breakfast, hidden):
        await client.post(
            f"{env.base}/items",
            json={
                "category_id": cat["id"],
                "name": f"G in {cat['name']}",
                "base_price_paise": 5000,
                "tax_class_id": env.tax_food["id"],
            },
            headers=owner(seed),
        )
    g = await new_guest(client, seed)
    menu = await g.menu()
    names = [c["name"] for c in menu["categories"]]
    assert "G Breakfast" not in names and "G Hidden" not in names
    starter = next(c for c in menu["categories"] if c["name"] == "G Starters")
    assert starter["items"][0]["available"] is False

    fake_clock.now = datetime(2026, 9, 18, 3, 30, tzinfo=UTC)  # 09:00 IST
    assert "G Breakfast" in [c["name"] for c in (await g.menu())["categories"]]


async def test_happy_hour_badge_and_lock_across_the_window_end(
    client: httpx.AsyncClient, seed: Seed, env: Menu, fake_clock: FakeClock
) -> None:
    """Golden flow 3: the price is locked when ordered, whatever happens next."""
    rule = (
        await client.post(
            f"{env.base}/price-rules",
            json={
                "name": "Happy hour",
                "scope": "item",
                "target_id": env.item["id"],
                "rule_type": "fixed",
                "value": 20000,
                "days_of_week": [0, 1, 2, 3, 4, 5, 6],
                "start_time": "18:00:00",
                "end_time": "20:00:00",
            },
            headers=owner(seed),
        )
    ).json()
    g = await new_guest(client, seed)
    item = next(i for c in (await g.menu())["categories"] for i in c["items"])
    assert item["price_paise"] == 20000 and item["base_price_paise"] == 32000
    assert item["price_rule"]["name"] == "Happy hour"
    assert item["price_rule"]["ends_at"].startswith("2026-09-18T20:00:00")

    placed = (await g.order([one(item, 2)])).json()
    line = placed["lines"][0]
    assert (line["unit_price_paise"], line["line_total_paise"]) == (20000, 40000)
    assert line["price_rule"] == {"id": rule["id"], "name": "Happy hour"}

    # The rule ends, the owner raises the price and deletes the rule.
    fake_clock.advance(90 * 60)
    await client.put(
        f"{env.base}/items/{env.item['id']}",
        json={
            "category_id": env.category["id"],
            "name": "G Paneer Tikka Deluxe",
            "base_price_paise": 45000,
            "tax_class_id": env.tax_food["id"],
        },
        headers=owner(seed),
    )
    assert (
        await client.delete(f"{env.base}/price-rules/{rule['id']}", headers=owner(seed))
    ).status_code == 204

    after = next(i for c in (await g.menu())["categories"] for i in c["items"])
    assert after["price_paise"] == 45000 and after["price_rule"] is None
    kept = (await g.tab())["rounds"][0]["lines"][0]
    assert kept["name"] == "G Paneer Tikka"
    assert (kept["unit_price_paise"], kept["line_total_paise"]) == (20000, 40000)
    assert kept["price_rule"] == {"id": rule["id"], "name": "Happy hour"}
    assert (await g.tab())["totals"]["items_paise"] == 40000


# --- placing orders -----------------------------------------------------------


async def _with_modifiers(client: httpx.AsyncClient, seed: Seed, env: Menu) -> dict[str, Any]:
    group = (
        await client.post(
            f"{env.base}/modifier-groups",
            json={
                "name": "G Spice",
                "min_select": 1,
                "max_select": 1,
                "modifiers": [{"name": "Mild"}, {"name": "Hot", "price_delta_paise": 1000}],
            },
            headers=owner(seed),
        )
    ).json()
    await client.put(
        f"{env.base}/items/{env.item['id']}",
        json={
            "category_id": env.category["id"],
            "name": env.item["name"],
            "base_price_paise": env.item["base_price_paise"],
            "tax_class_id": env.tax_food["id"],
            "modifier_group_ids": [group["id"]],
        },
        headers=owner(seed),
    )
    return dict(group)


async def test_placing_a_round_snapshots_everything_and_logs_events(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    group = await _with_modifiers(client, seed, env)
    hot = next(m["id"] for m in group["modifiers"] if m["name"] == "Hot")
    g = await new_guest(client, seed)
    r = await g.order([one(env.item, 2, modifier_ids=[hot], note="less oil")])
    assert r.status_code == 201, r.text
    rnd = r.json()
    assert (rnd["seq_no"], rnd["status"]) == (1, "placed")
    assert rnd["undo_until"] is not None
    line = rnd["lines"][0]
    assert line["name"] == "G Paneer Tikka" and line["qty"] == 2
    assert line["unit_price_paise"] == 32000
    assert line["modifiers"] == [{"name": "Hot", "price_delta_paise": 1000}]
    assert line["line_total_paise"] == 2 * 33000
    assert (line["placed_by"], line["by_you"], line["needs_customer_ack"]) == (
        "customer",
        True,
        False,
    )
    assert line["note"] == "less oil"

    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT tax_class_snapshot, modifiers_snapshot, item_name_snapshot "
                    "FROM order_line WHERE tab_id = :t"
                ),
                {"t": uuid.UUID(g.tab_id)},
            )
        ).one()
    assert row[0] == {
        "name": "G Food 5%",
        "rate_bp": 500,
        "is_liquor": False,
        "prices_include_tax": True,
    }
    assert row[1][0]["group_name"] == "G Spice"

    log = await events(owner_engine, g.tab_id)
    assert log == [
        ("opened", "customer"),
        ("line_added", "customer"),
        ("order_placed", "customer"),
    ]


async def test_second_round_gets_the_next_round_number(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    await g.order([one(env.item)])
    second = await g.order([one(env.item)])
    assert second.json()["seq_no"] == 2
    tab = await g.tab()
    assert [r["seq_no"] for r in tab["rounds"]] == [1, 2]


async def test_two_phones_share_one_tab_and_see_who_ordered(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    token = await table_token(client, seed)
    a = Guest(client, seed, (await scan(client, token)).json())
    b = Guest(client, seed, (await scan(client, token)).json())
    await a.order([one(env.item)])
    seen_by_b = (await b.tab())["rounds"][0]["lines"][0]
    assert seen_by_b["by_you"] is False
    assert (await a.tab())["rounds"][0]["lines"][0]["by_you"] is True


async def test_totals_split_tax_and_service_charge(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await client.patch(
        f"{env.base}/settings", json={"service_charge_bp": 1000}, headers=owner(seed)
    )
    g = await new_guest(client, seed)
    await g.order([one(env.item, 2)])
    totals = (await g.tab())["totals"]
    # 2 x 320.00 inclusive of 5% GST: taxable 609.52, tax 30.48 split 15.24 / 15.24.
    assert totals["items_paise"] == 64000
    assert (totals["taxable_value_paise"], totals["cgst_paise"], totals["sgst_paise"]) == (
        60952,
        1524,
        1524,
    )
    assert totals["service_charge_paise"] == 6095
    assert totals["estimated_total_paise"] == 64000 + 6095
    assert totals["is_estimate"] is True and totals["liquor_vat_paise"] == 0


async def test_removing_service_charge_is_logged_and_needs_no_reason(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await client.patch(
        f"{env.base}/settings", json={"service_charge_bp": 1000}, headers=owner(seed)
    )
    g = await new_guest(client, seed)
    await g.order([one(env.item)])
    before = (await g.tab())["totals"]
    r = await client.put(f"{g.base}/service-charge", json={"removed": True}, headers=g.headers())
    after = r.json()["totals"]
    assert after["service_charge_removed"] is True and after["service_charge_paise"] == 0
    assert after["taxable_value_paise"] == before["taxable_value_paise"]
    # Same value again is a no-op and does not add a second event.
    await client.put(f"{g.base}/service-charge", json={"removed": True}, headers=g.headers())
    restored = await client.put(
        f"{g.base}/service-charge", json={"removed": False}, headers=g.headers()
    )
    assert restored.json()["totals"]["service_charge_paise"] == before["service_charge_paise"]
    log = [e for e, _ in await events(owner_engine, g.tab_id)]
    assert log.count("service_charge_changed") == 2


async def test_cart_validation_errors(client: httpx.AsyncClient, seed: Seed, env: Menu) -> None:
    group = await _with_modifiers(client, seed, env)
    g = await new_guest(client, seed)
    missing = await g.order([one(env.item)])
    assert (missing.status_code, missing.json()["code"]) == (422, "invalid_modifiers")
    unknown = await g.order([{"menu_item_id": str(uuid.uuid4()), "qty": 1}])
    assert (unknown.status_code, unknown.json()["code"]) == (422, "unknown_item")
    zero = await g.order([one(env.item, 0)])
    assert (zero.status_code, zero.json()["code"]) == (422, "validation_error")
    assert (await g.order([])).status_code == 422
    off = await client.put(
        f"{env.base}/items/{env.item['id']}/availability",
        json={"available": False},
        headers=owner(seed),
    )
    assert off.status_code == 200
    mild = group["modifiers"][0]["id"]
    sold_out = await g.order([one(env.item, 1, modifier_ids=[mild])])
    assert (sold_out.status_code, sold_out.json()["code"]) == (409, "item_unavailable")
    assert (await g.tab())["rounds"] == []


async def test_other_restaurants_items_cannot_be_ordered(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    owner_b = hdr(seed.token(seed.owner_b, Role.OWNER, tenant="b"))
    base_b = f"/v1/outlets/{seed.outlet_b}"
    tax = (
        await client.post(
            f"{base_b}/tax-classes", json={"name": "B Food", "gst_rate_bp": 500}, headers=owner_b
        )
    ).json()
    cat = (
        await client.post(f"{base_b}/categories", json={"name": "B Cat"}, headers=owner_b)
    ).json()
    item_b = (
        await client.post(
            f"{base_b}/items",
            json={
                "category_id": cat["id"],
                "name": "B Dish",
                "base_price_paise": 1000,
                "tax_class_id": tax["id"],
            },
            headers=owner_b,
        )
    ).json()
    try:
        g = await new_guest(client, seed)
        r = await g.order([one(item_b)])
        assert (r.status_code, r.json()["code"]) == (422, "unknown_item")
    finally:
        await client.delete(f"{base_b}/items/{item_b['id']}", headers=owner_b)
        await client.delete(f"{base_b}/categories/{cat['id']}", headers=owner_b)
        await client.delete(f"{base_b}/tax-classes/{tax['id']}", headers=owner_b)


async def test_liquor_carries_the_outlets_vat_and_needs_waiter_when_restricted(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    await client.patch(
        f"{env.base}/settings",
        json={"liquor_licensed": True, "liquor_vat_rate_bp": 2000},
        headers=owner(seed),
    )
    beer = (
        await client.post(
            f"{env.base}/items",
            json={
                "category_id": env.category["id"],
                "name": "G Beer",
                "base_price_paise": 30000,
                "tax_class_id": env.tax_liquor["id"],
                "is_liquor": True,
                "needs_approval": True,
            },
            headers=owner(seed),
        )
    ).json()
    g = await new_guest(client, seed)
    ok = await g.order([one(beer)])
    assert ok.status_code == 201
    totals = (await g.tab())["totals"]
    assert (totals["liquor_vat_paise"], totals["cgst_paise"], totals["sgst_paise"]) == (5000, 0, 0)

    await client.patch(
        f"{env.base}/settings", json={"liquor_approval_required": True}, headers=owner(seed)
    )
    menu_beer = next(
        i for c in (await g.menu())["categories"] for i in c["items"] if i["name"] == "G Beer"
    )
    assert menu_beer["self_orderable"] is False
    blocked = await g.order([one(beer)])
    assert (blocked.status_code, blocked.json()["code"]) == (409, "needs_waiter")


async def test_exclusive_outlet_adds_tax_on_top(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE outlet SET prices_include_tax = false WHERE id = :o"), {"o": seed.outlet_a}
        )
    try:
        g = await new_guest(client, seed)
        await g.order([one(env.item)])
        totals = (await g.tab())["totals"]
        assert totals["prices_include_tax"] is False
        assert totals["estimated_total_paise"] == 32000 + 1600
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE outlet SET prices_include_tax = true WHERE id = :o"),
                {"o": seed.outlet_a},
            )


# --- cart quote ---------------------------------------------------------------


async def test_quote_matches_what_placing_the_order_then_shows(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await client.patch(
        f"{env.base}/settings", json={"service_charge_bp": 1000}, headers=owner(seed)
    )
    g = await new_guest(client, seed)
    body = {"lines": [one(env.item, 2)]}
    quote = await client.post(f"{g.base}/cart/quote", json=body, headers=g.headers())
    assert quote.status_code == 200, quote.text
    q = quote.json()
    assert q["can_order"] is True
    assert (q["lines"][0]["name"], q["lines"][0]["line_total_paise"]) == ("G Paneer Tikka", 64000)
    # Quoting writes nothing.
    assert (await g.tab())["rounds"] == []
    async with owner_engine.connect() as conn:
        n = await conn.scalar(
            text("SELECT count(*) FROM tab_event WHERE tab_id = :t"), {"t": uuid.UUID(g.tab_id)}
        )
    assert n == 1  # only "opened"

    await g.order(body["lines"])
    assert (await g.tab())["totals"] == q["totals"]


async def test_quote_reports_bad_carts_and_unconfirmed_tabs(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    await client.patch(
        f"{env.base}/settings", json={"waiter_confirm_mode": True}, headers=owner(seed)
    )
    g = await new_guest(client, seed)
    ok = await client.post(
        f"{g.base}/cart/quote", json={"lines": [one(env.item)]}, headers=g.headers()
    )
    assert ok.json()["can_order"] is False
    unknown = await client.post(
        f"{g.base}/cart/quote",
        json={"lines": [{"menu_item_id": str(uuid.uuid4()), "qty": 1}]},
        headers=g.headers(),
    )
    assert (unknown.status_code, unknown.json()["code"]) == (422, "unknown_item")
    other = await new_guest(client, seed, "T2")
    cross = await client.post(
        f"/v1/outlets/{g.outlet_id}/tabs/{other.tab_id}/cart/quote",
        json={"lines": [one(env.item)]},
        headers=g.headers(),
    )
    assert cross.status_code == 403


# --- idempotency --------------------------------------------------------------


async def test_replayed_order_returns_the_original_and_creates_one_round(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    key = uuid.uuid4()
    first = await g.order([one(env.item)], key)
    replay = await g.order([one(env.item)], key)
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert len((await g.tab())["rounds"]) == 1
    changed = await g.order([one(env.item, 3)], key)
    assert (changed.status_code, changed.json()["code"]) == (422, "idempotency_key_reused")


async def test_double_tap_race_places_one_round(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    key = uuid.uuid4()
    results = await asyncio.gather(*(g.order([one(env.item)], key) for _ in range(5)))
    ok = [r for r in results if r.status_code == 201]
    assert len(ok) >= 1
    assert len({r.json()["id"] for r in ok}) == 1
    assert {r.status_code for r in results} <= {201, 409}
    assert len((await g.tab())["rounds"]) == 1


async def test_same_key_from_two_phones_does_not_leak_between_them(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    token = await table_token(client, seed)
    a = Guest(client, seed, (await scan(client, token)).json())
    b = Guest(client, seed, (await scan(client, token)).json())
    key = uuid.uuid4()
    ra = await a.order([one(env.item)], key)
    rb = await b.order([one(env.item, 2)], key)
    assert ra.status_code == rb.status_code == 201
    assert ra.json()["id"] != rb.json()["id"]
    assert rb.json()["lines"][0]["qty"] == 2


# --- undo and auto-accept ------------------------------------------------------


async def test_undo_within_sixty_seconds_cancels_the_round(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item)])).json()
    fake_clock.advance(60)
    r = await client.post(f"{g.base}/orders/{placed['id']}/undo", headers=g.headers())
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and r.json()["lines"][0]["status"] == "cancelled"
    tab = await g.tab()
    assert tab["rounds"][0]["status"] == "cancelled"
    assert tab["totals"]["items_paise"] == 0
    log = [e for e, _ in await events(owner_engine, g.tab_id)]
    assert log[-1] == "order_cancelled"


async def test_undo_after_the_window_is_refused_and_round_is_accepted(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item)])).json()
    fake_clock.advance(61)
    r = await client.post(f"{g.base}/orders/{placed['id']}/undo", headers=g.headers())
    assert (r.status_code, r.json()["code"]) == (409, "undo_window_closed")
    assert r.json()["details"] == {"status": "accepted"}
    tab = await g.tab()
    assert tab["rounds"][0]["status"] == "accepted"
    assert tab["rounds"][0]["undo_until"] is None
    assert tab["rounds"][0]["lines"][0]["status"] == "accepted"
    await g.tab()
    log = [e for e, _ in await events(owner_engine, g.tab_id)]
    assert log.count("order_accepted") == 1


async def test_auto_accept_via_read_alone(
    client: httpx.AsyncClient, seed: Seed, env: Menu, fake_clock: FakeClock
) -> None:
    g = await new_guest(client, seed)
    await g.order([one(env.item)])
    fake_clock.advance(59)
    assert (await g.tab())["rounds"][0]["status"] == "placed"
    fake_clock.advance(2)
    assert (await g.tab())["rounds"][0]["status"] == "accepted"


async def test_only_the_placing_phone_may_undo(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    token = await table_token(client, seed)
    a = Guest(client, seed, (await scan(client, token)).json())
    b = Guest(client, seed, (await scan(client, token)).json())
    placed = (await a.order([one(env.item)])).json()
    r = await client.post(f"{b.base}/orders/{placed['id']}/undo", headers=b.headers())
    assert (r.status_code, r.json()["code"]) == (403, "not_your_order")
    missing = await client.post(f"{a.base}/orders/{uuid.uuid4()}/undo", headers=a.headers())
    assert missing.status_code == 404


async def test_undo_of_an_already_cancelled_round_is_refused(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item)])).json()
    assert (
        await client.post(f"{g.base}/orders/{placed['id']}/undo", headers=g.headers())
    ).status_code == 200
    again = await client.post(f"{g.base}/orders/{placed['id']}/undo", headers=g.headers())
    assert (again.status_code, again.json()["code"]) == (409, "undo_window_closed")


async def test_undo_is_idempotent_with_a_key(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item)])).json()
    key = uuid.uuid4()
    first = await client.post(f"{g.base}/orders/{placed['id']}/undo", headers=g.headers(key))
    replay = await client.post(f"{g.base}/orders/{placed['id']}/undo", headers=g.headers(key))
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()


# --- waiter-confirm mode ------------------------------------------------------


async def test_waiter_confirm_mode_blocks_ordering_until_a_waiter_confirms(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await client.patch(
        f"{env.base}/settings", json={"waiter_confirm_mode": True}, headers=owner(seed)
    )
    g = await new_guest(client, seed)
    assert (await g.tab())["awaiting_waiter"] is True
    assert (await g.menu())["categories"]  # browsing is allowed
    blocked = await g.order([one(env.item)])
    assert (blocked.status_code, blocked.json()["code"]) == (409, "awaiting_waiter")

    confirm = f"{g.base}/confirm"
    kitchen = hdr(seed.token(seed.kitchen_a, Role.KITCHEN))
    assert (await client.post(confirm, headers=kitchen)).status_code == 403
    assert (await client.post(confirm)).status_code == 401
    wrong_tenant = hdr(seed.token(seed.manager_b, Role.MANAGER, tenant="b"))
    assert (await client.post(confirm, headers=wrong_tenant)).status_code == 403

    waiter = hdr(seed.token(seed.waiter_a, Role.WAITER))
    ok = await client.post(confirm, headers=waiter)
    assert ok.status_code == 200, ok.text
    again = await client.post(confirm, headers=waiter)
    assert again.json()["confirmed_at"] == ok.json()["confirmed_at"]
    assert (await g.tab())["awaiting_waiter"] is False
    assert (await g.order([one(env.item)])).status_code == 201
    log = [e for e, _ in await events(owner_engine, g.tab_id)]
    assert log.count("confirmed") == 1


async def test_a_table_can_require_confirmation_on_its_own(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    tables = (await client.get(f"/v1/outlets/{seed.outlet_a}/tables", headers=owner(seed))).json()
    t1 = next(t for t in tables if t["label"] == "T1")
    await client.put(
        f"/v1/outlets/{seed.outlet_a}/tables/{t1['id']}",
        json={"label": "T1", "requires_waiter_confirm": True},
        headers=owner(seed),
    )
    g = await new_guest(client, seed)
    assert (await g.tab())["awaiting_waiter"] is True


async def test_confirming_a_tab_in_another_outlet_or_unknown_tab_is_404_or_403(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    waiter = hdr(seed.token(seed.waiter_a, Role.WAITER))
    r = await client.post(
        f"/v1/outlets/{seed.outlet_a}/tabs/{uuid.uuid4()}/confirm", headers=waiter
    )
    assert r.status_code == 404


async def test_confirming_a_closed_tab_is_refused(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    g = await new_guest(client, seed)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE tab SET status = 'closed' WHERE id = :t"), {"t": uuid.UUID(g.tab_id)}
        )
    waiter = hdr(seed.token(seed.waiter_a, Role.WAITER))
    r = await client.post(f"{g.base}/confirm", headers=waiter)
    assert (r.status_code, r.json()["code"]) == (409, "tab_not_open")


# --- service requests ---------------------------------------------------------


async def test_calling_the_waiter_twice_rings_once(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    g = await new_guest(client, seed)
    first = await client.post(
        f"{g.base}/service-requests", json={"type": "waiter"}, headers=g.headers()
    )
    second = await client.post(
        f"{g.base}/service-requests", json={"type": "waiter"}, headers=g.headers()
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    water = await client.post(
        f"{g.base}/service-requests", json={"type": "water"}, headers=g.headers()
    )
    assert water.json()["id"] != first.json()["id"]
    assert (await g.tab())["open_requests"] == ["waiter", "water"]
    log = [e for e, _ in await events(owner_engine, g.tab_id)]
    assert log.count("service_requested") == 2
    bad = await client.post(
        f"{g.base}/service-requests", json={"type": "gossip"}, headers=g.headers()
    )
    assert bad.status_code == 422


async def test_bill_request_needs_an_order_and_flags_the_tab(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    g = await new_guest(client, seed)
    early = await client.post(
        f"{g.base}/service-requests", json={"type": "bill"}, headers=g.headers()
    )
    assert (early.status_code, early.json()["code"]) == (409, "nothing_to_bill")

    await g.order([one(env.item)])
    r = await client.post(f"{g.base}/service-requests", json={"type": "bill"}, headers=g.headers())
    assert (r.status_code, r.json()["tab_status"]) == (201, "bill_requested")
    assert (await g.tab())["status"] == "bill_requested"

    # More items reopen the tab; asking for the bill again flags it again.
    await g.order([one(env.item)])
    assert (await g.tab())["status"] == "open"
    again = await client.post(
        f"{g.base}/service-requests", json={"type": "bill"}, headers=g.headers()
    )
    assert again.json()["tab_status"] == "bill_requested"
    log = [e for e, _ in await events(owner_engine, g.tab_id)]
    assert log.count("bill_requested") == 2 and log.count("bill_request_cleared") == 1


async def test_bill_request_is_refused_when_everything_was_undone(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item)])).json()
    await client.post(f"{g.base}/orders/{placed['id']}/undo", headers=g.headers())
    r = await client.post(f"{g.base}/service-requests", json={"type": "bill"}, headers=g.headers())
    assert r.json()["code"] == "nothing_to_bill"


async def test_voided_lines_stay_visible_but_leave_the_total(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    g = await new_guest(client, seed)
    await g.order([one(env.item), one(env.item, 2)])
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE order_line SET status = 'voided', voided_at = now(), "
                "void_reason = 'wrong table' WHERE tab_id = :t AND qty = 2"
            ),
            {"t": uuid.UUID(g.tab_id)},
        )
    tab = await g.tab()
    voided = next(line for line in tab["rounds"][0]["lines"] if line["qty"] == 2)
    assert (voided["status"], voided["void_reason"]) == ("voided", "wrong table")
    assert tab["totals"]["items_paise"] == 32000


# --- database-level guarantees --------------------------------------------------


async def test_app_role_cannot_rewrite_or_delete_the_event_log(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    for statement in ("UPDATE tab_event SET reason = 'x'", "DELETE FROM tab_event"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with tenant_session(seed.restaurant_a) as session:
                await session.execute(text(statement))
    async with tenant_session(seed.restaurant_a) as session:
        count = await session.scalar(
            text("SELECT count(*) FROM tab_event WHERE tab_id = :t"), {"t": uuid.UUID(g.tab_id)}
        )
    assert count == 1


async def test_tab_rows_are_invisible_to_another_tenant(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    await g.order([one(env.item)])
    async with tenant_session(seed.restaurant_b) as session:
        for table in ("tab", "tab_session", "tab_order", "order_line", "tab_event"):
            rows = await session.scalar(text(f"SELECT count(*) FROM {table}"))
            assert rows == 0, table


async def test_rescan_with_a_bad_or_foreign_token_issues_a_fresh_session(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    token = await table_token(client, seed)
    first = (await scan(client, token)).json()
    for bad in ("garbage", f"{seed.restaurant_b.hex}.{first['session_token'].split('.', 1)[1]}"):
        again = (await scan(client, token, bad)).json()
        assert again["session_token"] not in (None, first["session_token"])
        assert again["tab_id"] == first["tab_id"]


async def test_staff_added_lines_show_the_waiters_name_and_ack_flag(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    """Staff can't add lines until Milestone 4, but the guest view and the table's
    constraints must already handle them."""
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item)])).json()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE app_user SET name = 'Ravi' WHERE id = :u"), {"u": seed.waiter_a}
        )
        await conn.execute(
            text(
                "INSERT INTO order_line (id, restaurant_id, order_id, tab_id, menu_item_id, "
                "item_name_snapshot, qty, unit_price_snapshot, tax_class_snapshot, line_total, "
                "placed_by, staff_user_id, needs_customer_ack) "
                "SELECT gen_random_uuid(), restaurant_id, order_id, tab_id, menu_item_id, "
                "'Whisky', 1, 52000, tax_class_snapshot, 52000, 'staff', :u, true "
                "FROM order_line WHERE order_id = :o LIMIT 1"
            ),
            {"u": seed.waiter_a, "o": uuid.UUID(placed["id"])},
        )
    lines = (await g.tab())["rounds"][0]["lines"]
    staff_line = next(line for line in lines if line["placed_by"] == "staff")
    assert staff_line["staff_name"] == "Ravi" and staff_line["needs_customer_ack"] is True
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE app_user SET name = NULL WHERE id = :u"), {"u": seed.waiter_a}
        )


async def test_staff_line_constraints_reject_inconsistent_rows(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item)])).json()
    base = (
        "INSERT INTO order_line (id, restaurant_id, order_id, tab_id, menu_item_id, "
        "item_name_snapshot, qty, unit_price_snapshot, tax_class_snapshot, line_total, "
        "placed_by, staff_user_id, needs_customer_ack, voided_at) "
        "SELECT gen_random_uuid(), restaurant_id, order_id, tab_id, menu_item_id, 'X', 1, 1, "
        "tax_class_snapshot, 1, {values} FROM order_line WHERE order_id = :o LIMIT 1"
    )
    bad_values = [
        "'staff', NULL, false, NULL",  # staff line must record who
        "'customer', :u, false, NULL",  # customer line cannot name staff
        "'customer', NULL, true, NULL",  # only staff lines need acknowledgement
        "'customer', NULL, false, now()",  # a void needs a reason
    ]
    for values in bad_values:
        with pytest.raises(DBAPIError):
            async with owner_engine.begin() as conn:
                await conn.execute(
                    text(base.format(values=values)),
                    {"o": uuid.UUID(placed["id"]), "u": seed.waiter_a},
                )
