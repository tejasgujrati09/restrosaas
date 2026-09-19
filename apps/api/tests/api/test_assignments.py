"""Waiters see only their tables; managers assign them."""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.permissions import Role
from tests.api.guest_helpers import (
    assign,
    floor,
    kitchen,
    manager,
    new_guest,
    staff,
    waiter,
)
from tests.api.helpers import Menu
from tests.conftest import Seed, hdr


def base(seed: Seed) -> str:
    return f"/v1/outlets/{seed.outlet_a}"


async def table_ids(client: httpx.AsyncClient, seed: Seed) -> dict[str, str]:
    rows = (await client.get(f"{base(seed)}/table-assignments", headers=manager(seed))).json()
    return {r["label"]: r["table_id"] for r in rows}


async def test_a_manager_assigns_a_waiter_and_the_list_shows_it(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    ids = await table_ids(client, seed)
    r = await client.put(
        f"{base(seed)}/tables/{ids['T1']}/assignees",
        json={"user_ids": [str(seed.waiter_a)]},
        headers=manager(seed),
    )
    assert r.status_code == 200, r.text
    by_label = {row["label"]: row["waiters"] for row in r.json()}
    assert [w["user_id"] for w in by_label["T1"]] == [str(seed.waiter_a)]
    assert by_label["T2"] == []
    # Replacing, not adding: an empty list clears the table.
    cleared = await client.put(
        f"{base(seed)}/tables/{ids['T1']}/assignees", json={"user_ids": []}, headers=manager(seed)
    )
    assert {row["label"]: row["waiters"] for row in cleared.json()}["T1"] == []


async def test_only_managers_and_owners_may_assign(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    ids = await table_ids(client, seed)
    url = f"{base(seed)}/tables/{ids['T1']}/assignees"
    body = {"user_ids": [str(seed.waiter_a)]}
    for who in (waiter(seed), kitchen(seed)):
        assert (await client.put(url, json=body, headers=who)).status_code == 403
        assert (await client.get(f"{base(seed)}/table-assignments", headers=who)).status_code == 403
    assert (await client.put(url, json=body)).status_code == 401
    owner = staff(seed, seed.owner_a, Role.OWNER)
    assert (await client.put(url, json=body, headers=owner)).status_code == 200
    # Another restaurant's manager has no claim on this outlet at all.
    outsider = hdr(seed.token(seed.manager_b, Role.MANAGER, tenant="b"))
    assert (await client.put(url, json=body, headers=outsider)).status_code == 403


async def test_only_active_waiters_of_this_outlet_can_be_assigned(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    ids = await table_ids(client, seed)
    url = f"{base(seed)}/tables/{ids['T1']}/assignees"
    for bad in (seed.kitchen_a, seed.inactive_waiter_a, seed.owner_b, uuid.uuid4()):
        r = await client.put(url, json={"user_ids": [str(bad)]}, headers=manager(seed))
        assert (r.status_code, r.json()["code"]) == (422, "not_a_waiter"), bad
    unknown = await client.put(
        f"{base(seed)}/tables/{uuid.uuid4()}/assignees",
        json={"user_ids": []},
        headers=manager(seed),
    )
    assert unknown.status_code == 404
    other_outlet_table = await client.put(
        f"{base(seed)}/tables/{uuid.uuid4()}/assignees",
        json={"user_ids": []},
        headers=manager(seed),
    )
    assert other_outlet_table.status_code == 404


async def test_a_zone_can_be_assigned_in_one_go(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    r = await client.put(
        f"{base(seed)}/table-assignments/zone",
        json={"zone": "floor", "user_ids": [str(seed.waiter_a)]},
        headers=manager(seed),
    )
    assert r.status_code == 200
    assert all(len(row["waiters"]) == 1 for row in r.json() if row["label"] in ("T1", "T2"))
    missing = await client.put(
        f"{base(seed)}/table-assignments/zone",
        json={"zone": "rooftop", "user_ids": []},
        headers=manager(seed),
    )
    assert missing.status_code == 404


async def test_a_waiter_sees_only_their_tables_and_a_manager_sees_all(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    empty = (await client.get(f"{floor(seed)}/table-map", headers=waiter(seed))).json()
    assert empty == {"tables": [], "unassigned": True}

    await assign(owner_engine, seed, "T1")
    mine = (await client.get(f"{floor(seed)}/table-map", headers=waiter(seed))).json()
    assert [t["label"] for t in mine["tables"]] == ["T1"] and mine["unassigned"] is False
    everyone = (await client.get(f"{floor(seed)}/table-map", headers=manager(seed))).json()
    assert {t["label"] for t in everyone["tables"]} >= {"T1", "T2"}
    assert everyone["unassigned"] is False


async def test_a_waiter_cannot_reach_an_unassigned_tables_tab(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    theirs = await new_guest(client, seed, "T2")
    await assign(owner_engine, seed, "T1")
    url = f"{floor(seed)}/tabs/{theirs.tab_id}"
    for method, path, body in (
        ("GET", url, None),
        ("POST", f"{url}/orders", {"lines": [{"menu_item_id": str(uuid.uuid4()), "qty": 1}]}),
        ("POST", f"{url}/transfer", {"table_id": str(uuid.uuid4())}),
        ("POST", f"{url}/merge", {"into_tab_id": str(uuid.uuid4())}),
    ):
        r = await client.request(method, path, json=body, headers=waiter(seed))
        assert (r.status_code, r.json()["code"]) == (404, "not_found"), path
    assert (await client.get(url, headers=manager(seed))).status_code == 200
    confirm = await client.post(
        f"/v1/outlets/{seed.outlet_a}/tabs/{theirs.tab_id}/confirm", headers=waiter(seed)
    )
    assert confirm.status_code == 404
    # Deactivated staff lose everything even with a valid token.
    ghost = staff(seed, seed.inactive_waiter_a, Role.WAITER)
    assert (await client.get(f"{floor(seed)}/table-map", headers=ghost)).status_code == 403
