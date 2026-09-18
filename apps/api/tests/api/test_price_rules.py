from __future__ import annotations

import httpx
import pytest

from app.core.permissions import Role
from tests.api.helpers import Menu, build_menu, cleanup_menu
from tests.conftest import Seed, hdr


@pytest.fixture
async def menu(client: httpx.AsyncClient, seed: Seed):  # type: ignore[no-untyped-def]
    built = await build_menu(client, seed, "P")
    yield built
    rules = (await client.get(f"{built.base}/price-rules", headers=built.owner)).json()
    for rule in rules:
        await client.delete(f"{built.base}/price-rules/{rule['id']}", headers=built.owner)
    await cleanup_menu(client, built)


def rule(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "P Happy hour",
        "scope": "all",
        "target_id": None,
        "rule_type": "percent_off",
        "value": 5000,
        "days_of_week": [0, 1, 2, 3, 4, 5, 6],
        "start_time": "17:00:00",
        "end_time": "20:00:00",
        "active": True,
    }
    body.update(over)
    return body


async def price_at(client: httpx.AsyncClient, menu: Menu, at: str) -> dict[str, object]:
    r = await client.get(
        f"{menu.base}/menu/effective-prices", params={"at": at}, headers=menu.owner
    )
    assert r.status_code == 200
    (only,) = r.json()
    return only


async def test_manager_can_manage_price_rules_but_waiter_cannot(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    manager = hdr(seed.token(seed.manager_a, Role.MANAGER))
    waiter = hdr(seed.token(seed.waiter_a, Role.WAITER))
    created = await client.post(f"{menu.base}/price-rules", json=rule(), headers=manager)
    assert created.status_code == 201
    assert (
        await client.post(f"{menu.base}/price-rules", json=rule(name="P2"), headers=waiter)
    ).status_code == 403
    listed = await client.get(
        f"{menu.base}/price-rules", headers=waiter
    )  # anyone on staff may read
    assert [r["name"] for r in listed.json()] == ["P Happy hour"]


async def test_happy_hour_applies_in_outlet_timezone_and_records_rule_id(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    created = (
        await client.post(f"{menu.base}/price-rules", json=rule(), headers=menu.owner)
    ).json()
    inside = await price_at(client, menu, "2026-09-18T18:00:00+05:30")
    assert (inside["unit_price_paise"], inside["price_rule_id"]) == (16000, created["id"])
    # The same instant expressed in UTC (12:30Z) is still 18:00 in Kolkata.
    same = await price_at(client, menu, "2026-09-18T12:30:00Z")
    assert same["unit_price_paise"] == 16000
    outside = await price_at(client, menu, "2026-09-18T20:00:00+05:30")
    assert (outside["unit_price_paise"], outside["price_rule_id"]) == (32000, None)


async def test_window_crossing_midnight_and_item_scope_precedence(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    late = {"start_time": "22:00:00", "end_time": "02:00:00", "days_of_week": [4]}  # Friday night
    await client.post(
        f"{menu.base}/price-rules", json=rule(name="P Late", **late), headers=menu.owner
    )
    saturday_1am = await price_at(client, menu, "2026-09-19T01:00:00+05:30")
    assert saturday_1am["unit_price_paise"] == 16000
    item_rule = (
        await client.post(
            f"{menu.base}/price-rules",
            json=rule(
                name="P Item",
                scope="item",
                target_id=menu.item["id"],
                rule_type="fixed",
                value=25000,
                **late,
            ),
            headers=menu.owner,
        )
    ).json()
    winner = await price_at(client, menu, "2026-09-18T23:00:00+05:30")
    assert (winner["unit_price_paise"], winner["price_rule_id"]) == (25000, item_rule["id"])


async def test_validation(client: httpx.AsyncClient, seed: Seed, menu: Menu) -> None:
    async def status(**over: object) -> int:
        return (
            await client.post(f"{menu.base}/price-rules", json=rule(**over), headers=menu.owner)
        ).status_code

    assert await status(start_time="20:00:00", end_time="20:00:00") == 422
    assert await status(rule_type="percent_off", value=10001) == 422
    assert await status(days_of_week=[]) == 422
    assert await status(days_of_week=[7]) == 422
    assert await status(days_of_week=[1, 1]) == 422
    assert await status(scope="item", target_id=None) == 422
    assert await status(scope="all", target_id=menu.item["id"]) == 422
    assert await status(valid_from="2026-09-18T00:00:00") == 422  # naive datetime
    assert (
        await status(valid_from="2026-09-20T00:00:00+05:30", valid_to="2026-09-19T00:00:00+05:30")
        == 422
    )
    missing = await client.post(
        f"{menu.base}/price-rules",
        json=rule(scope="category", target_id="00000000-0000-0000-0000-000000000001"),
        headers=menu.owner,
    )
    assert (missing.status_code, missing.json()["details"]["field"]) == (422, "target_id")
    bad_item = await client.post(
        f"{menu.base}/price-rules",
        json=rule(scope="item", target_id="00000000-0000-0000-0000-000000000001"),
        headers=menu.owner,
    )
    assert bad_item.status_code == 422


async def test_update_delete_and_valid_window(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    created = (
        await client.post(f"{menu.base}/price-rules", json=rule(), headers=menu.owner)
    ).json()
    updated = await client.put(
        f"{menu.base}/price-rules/{created['id']}",
        json=rule(
            value=2500,
            valid_from="2026-09-01T00:00:00+05:30",
            valid_to="2026-09-30T00:00:00+05:30",
            days_of_week=[4, 0],
        ),
        headers=menu.owner,
    )
    assert updated.json()["value"] == 2500 and updated.json()["days_of_week"] == [0, 4]
    before = await price_at(client, menu, "2026-08-31T18:00:00+05:30")
    assert before["price_rule_id"] is None  # before valid_from
    assert (
        await client.put(
            f"{menu.base}/price-rules/{menu.item['id']}", json=rule(), headers=menu.owner
        )
    ).status_code == 404
    assert (
        await client.delete(f"{menu.base}/price-rules/{created['id']}", headers=menu.owner)
    ).status_code == 204
    assert (
        await client.delete(f"{menu.base}/price-rules/{created['id']}", headers=menu.owner)
    ).status_code == 404


async def test_effective_prices_requires_timezone_and_defaults_to_now(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    naive = await client.get(
        f"{menu.base}/menu/effective-prices",
        params={"at": "2026-09-18T18:00:00"},
        headers=menu.owner,
    )
    assert naive.status_code == 422
    now = await client.get(f"{menu.base}/menu/effective-prices", headers=menu.owner)
    assert now.status_code == 200 and now.json()[0]["unit_price_paise"] == 32000


async def test_price_rules_are_tenant_scoped(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    created = (
        await client.post(f"{menu.base}/price-rules", json=rule(), headers=menu.owner)
    ).json()
    other = hdr(seed.token(seed.owner_b, Role.OWNER, tenant="b"))
    assert (await client.get(f"{menu.base}/price-rules", headers=other)).status_code == 403
    via_b = await client.delete(
        f"/v1/outlets/{seed.outlet_b}/price-rules/{created['id']}", headers=other
    )
    assert via_b.status_code == 404
