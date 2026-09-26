"""Bulk assignment, the board, and automatic assignment of unassigned tables."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.permissions import Role
from tests.api.guest_helpers import Guest, events, floor, manager, new_guest, one, waiter, wipe_tabs
from tests.api.helpers import Menu, build_menu, cleanup_menu
from tests.conftest import Seed, hdr, new_phone


def base(seed: Seed) -> str:
    return f"/v1/outlets/{seed.outlet_a}"


@dataclass
class Stage:
    seed: Seed
    client: httpx.AsyncClient
    engine: AsyncEngine
    menu: Menu
    w1: uuid.UUID  # the seed waiter
    w2: uuid.UUID
    w3: uuid.UUID

    async def configure(self, enabled: bool, strategy: str = "least_loaded") -> httpx.Response:
        return await self.client.put(
            f"{base(self.seed)}/table-assignments/auto",
            json={"enabled": enabled, "strategy": strategy},
            headers=manager(self.seed),
        )

    async def board(self) -> dict[str, Any]:
        r = await self.client.get(
            f"{base(self.seed)}/table-assignments/board", headers=manager(self.seed)
        )
        assert r.status_code == 200, r.text
        return dict(r.json())

    async def card(self, label: str) -> dict[str, Any]:
        return next(t for t in (await self.board())["tables"] if t["label"] == label)

    async def waiters_of(self, label: str) -> set[str]:
        return {w["user_id"] for w in (await self.card(label))["waiters"]}

    async def table_id(self, label: str) -> str:
        return str((await self.card(label))["table_id"])

    async def guest_orders(self, label: str) -> Guest:
        guest = await new_guest(self.client, self.seed, label)
        r = await guest.order([one(self.menu.item)])
        assert r.status_code == 201, r.text
        return guest

    async def bulk(
        self, labels: list[str], users: list[uuid.UUID], key: uuid.UUID | None = None
    ) -> httpx.Response:
        ids = [await self.table_id(label) for label in labels]
        return await self.client.put(
            f"{base(self.seed)}/table-assignments/bulk",
            json={"table_ids": ids, "user_ids": [str(u) for u in users]},
            headers=hdr(self.seed.token(self.seed.manager_a, Role.MANAGER), key),
        )


async def _add_waiter(engine: AsyncEngine, seed: Seed, name: str) -> uuid.UUID:
    user = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO app_user (id, phone, name) VALUES (:id, :p, :n)"),
            {"id": user, "p": new_phone(), "n": name},
        )
        await conn.execute(
            text(
                "INSERT INTO staff_role (id, restaurant_id, user_id, outlet_id, role, active) "
                "VALUES (gen_random_uuid(), :r, :u, :o, 'waiter', true)"
            ),
            {"r": seed.restaurant_a, "u": user, "o": seed.outlet_a},
        )
    return user


@pytest.fixture
async def stage(
    client: httpx.AsyncClient, seed: Seed, owner_engine: AsyncEngine
) -> AsyncIterator[Stage]:
    await wipe_tabs(owner_engine, seed)
    menu = await build_menu(client, seed, "A")
    w2 = await _add_waiter(owner_engine, seed, "Amit")
    w3 = await _add_waiter(owner_engine, seed, "Priya")
    owner = menu.owner
    for label, zone in (("T3", "floor"), ("B1", "bar"), ("B2", "bar")):
        r = await client.post(
            f"{base(seed)}/tables", json={"label": label, "zone": zone}, headers=owner
        )
        assert r.status_code == 201, r.text
    yield Stage(seed, client, owner_engine, menu, seed.waiter_a, w2, w3)
    await wipe_tabs(owner_engine, seed)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE outlet SET auto_assign_unassigned_table_orders = false, "
                "auto_assignment_strategy = 'least_loaded', assignment_rotation_last_user_id = NULL "
                "WHERE id = :o"
            ),
            {"o": seed.outlet_a},
        )
        await conn.execute(
            text("UPDATE staff_role SET active = true WHERE user_id = :u"), {"u": seed.waiter_a}
        )
        await conn.execute(
            text("DELETE FROM dining_table WHERE outlet_id = :o AND label IN ('T3', 'B1', 'B2')"),
            {"o": seed.outlet_a},
        )
        await conn.execute(text("DELETE FROM staff_role WHERE user_id = ANY(:u)"), {"u": [w2, w3]})
        await conn.execute(text("DELETE FROM app_user WHERE id = ANY(:u)"), {"u": [w2, w3]})
    await cleanup_menu(client, menu)


# ---- the board and bulk assignment --------------------------------------------------------


async def test_board_lists_cards_waiters_and_config(stage: Stage) -> None:
    board = await stage.board()
    assert board["config"] == {"enabled": False, "strategy": "least_loaded"}
    assert {t["label"] for t in board["tables"]} >= {"T1", "T2", "T3", "B1", "B2"}
    assert {w["user_id"] for w in board["waiters"]} == {
        str(stage.w1),
        str(stage.w2),
        str(stage.w3),
    }  # the inactive waiter is not offered
    card = await stage.card("T1")
    assert (card["state"], card["waiters"], card["needs_waiter"]) == ("empty", [], False)


async def test_bulk_assign_replaces_waiters_and_leaves_tabs_alone(stage: Stage) -> None:
    guest = await stage.guest_orders("T1")
    before = (await stage.card("T1"))["state"]
    assert before == "order_pending"

    r = await stage.bulk(["T1", "T2", "T3"], [stage.w2])
    assert r.status_code == 200, r.text
    tables = {t["label"]: t for t in r.json()["tables"]}
    assert all(
        [w["user_id"] for w in tables[label]["waiters"]] == [str(stage.w2)]
        for label in ("T1", "T2", "T3")
    )
    assert tables["T1"]["state"] == before  # the guest's tab and order are undisturbed
    assert (await guest.tab())["status"] == "open"

    r = await stage.bulk(["T1", "T2"], [stage.w3])  # changing the waiter replaces
    tables = {t["label"]: t for t in r.json()["tables"]}
    assert [w["user_id"] for w in tables["T1"]["waiters"]] == [str(stage.w3)]
    assert [w["user_id"] for w in tables["T3"]["waiters"]] == [str(stage.w2)]
    assert tables["T1"]["auto_assigned"] is False
    counts = {w["user_id"]: w["tables"] for w in r.json()["waiters"]}
    assert (counts[str(stage.w2)], counts[str(stage.w3)]) == (1, 2)

    cleared = await stage.bulk(["T1", "T2", "T3"], [])
    assert all(t["waiters"] == [] for t in cleared.json()["tables"])


async def test_bulk_assign_is_idempotent_validated_and_role_checked(stage: Stage) -> None:
    key = uuid.uuid4()
    first = await stage.bulk(["T1"], [stage.w2], key)
    assert (await stage.bulk(["T1"], [stage.w2], key)).json() == first.json()
    assert (await stage.bulk(["T2"], [stage.w2], key)).json()["code"] == "idempotency_key_reused"

    bad = await stage.bulk(["T1"], [stage.seed.kitchen_a])
    assert (bad.status_code, bad.json()["code"]) == (422, "not_a_waiter")
    missing = await stage.client.put(
        f"{base(stage.seed)}/table-assignments/bulk",
        json={"table_ids": [str(uuid.uuid4())], "user_ids": []},
        headers=manager(stage.seed),
    )
    assert missing.status_code == 404
    other_tenant = await stage.client.put(
        f"{base(stage.seed)}/table-assignments/bulk",
        json={"table_ids": [await stage.table_id("T1")], "user_ids": []},
        headers=hdr(stage.seed.token(stage.seed.manager_b, Role.MANAGER, tenant="b")),
    )
    assert other_tenant.status_code == 403
    empty = await stage.client.put(
        f"{base(stage.seed)}/table-assignments/bulk",
        json={"table_ids": [], "user_ids": []},
        headers=manager(stage.seed),
    )
    assert empty.status_code == 422
    for who in (waiter(stage.seed), hdr(stage.seed.token(stage.seed.kitchen_a, Role.KITCHEN))):
        url = f"{base(stage.seed)}/table-assignments"
        assert (await stage.client.get(f"{url}/board", headers=who)).status_code == 403
        assert (
            await stage.client.put(
                f"{url}/auto", json={"enabled": True, "strategy": "rotation"}, headers=who
            )
        ).status_code == 403
        assert (
            await stage.client.put(
                f"{url}/bulk", json={"table_ids": [str(uuid.uuid4())], "user_ids": []}, headers=who
            )
        ).status_code == 403


async def test_configuration_is_saved_audited_and_shown_in_settings(stage: Stage) -> None:
    r = await stage.configure(True, "rotation")
    assert r.status_code == 200 and r.json()["config"] == {"enabled": True, "strategy": "rotation"}
    settings = (
        await stage.client.get(f"{base(stage.seed)}/settings", headers=stage.menu.owner)
    ).json()
    assert (
        settings["auto_assign_unassigned_table_orders"],
        settings["auto_assignment_strategy"],
    ) == (True, "rotation")
    off = await stage.configure(False, "rotation")  # the strategy is kept while off
    assert off.json()["config"] == {"enabled": False, "strategy": "rotation"}
    bad = await stage.client.put(
        f"{base(stage.seed)}/table-assignments/auto",
        json={"enabled": True, "strategy": "random"},
        headers=manager(stage.seed),
    )
    assert bad.status_code == 422
    async with stage.engine.connect() as conn:
        n = await conn.scalar(
            text(
                "SELECT count(*) FROM audit_log WHERE action = 'assignment.auto_changed' AND restaurant_id = :r"
            ),
            {"r": stage.seed.restaurant_a},
        )
    assert n and n >= 2


# ---- flag off: manual ---------------------------------------------------------------------


async def test_with_automatic_assignment_off_the_order_waits_for_a_manager(stage: Stage) -> None:
    await stage.guest_orders("T1")
    card = await stage.card("T1")
    assert card["waiters"] == [] and card["needs_waiter"] is True
    (waiting,) = card["waiting_orders"]
    assert waiting["status"] == "placed" and len(waiting["short_id"]) > 0
    assert (await stage.board())["tables"] and not (await stage.card("T2"))["needs_waiter"]

    # The waiter cannot see it yet; the manager hands it over and the waiter can.
    mine = (
        await stage.client.get(f"{floor(stage.seed)}/table-map", headers=waiter(stage.seed))
    ).json()
    assert mine["tables"] == []
    assert (await stage.bulk(["T1"], [stage.w1])).status_code == 200
    mine = (
        await stage.client.get(f"{floor(stage.seed)}/table-map", headers=waiter(stage.seed))
    ).json()
    assert [t["label"] for t in mine["tables"]] == ["T1"]
    assert (await stage.card("T1"))["needs_waiter"] is False


# ---- flag on ------------------------------------------------------------------------------


async def test_an_existing_assignment_is_never_overridden(stage: Stage) -> None:
    await stage.configure(True, "rotation")
    await stage.bulk(["T1"], [stage.w2])
    guest = await stage.guest_orders("T1")
    assert await stage.waiters_of("T1") == {str(stage.w2)}
    assert (await stage.card("T1"))["auto_assigned"] is False
    assert await guest.order([one(stage.menu.item)])  # a second round changes nothing either
    assert await stage.waiters_of("T1") == {str(stage.w2)}


async def test_least_loaded_picks_the_waiter_with_fewest_busy_tables(stage: Stage) -> None:
    await stage.configure(True, "least_loaded")
    await stage.bulk(["T2"], [stage.w1])
    await stage.bulk(["T3"], [stage.w2])
    await stage.guest_orders("T2")
    await stage.guest_orders("T3")  # w1 and w2 each have one busy table; w3 has none
    await stage.guest_orders("T1")
    assert await stage.waiters_of("T1") == {str(stage.w3)}
    card = await stage.card("T1")
    assert card["auto_assigned"] is True and card["needs_waiter"] is False


async def test_a_lightly_loaded_waiter_beats_one_with_many_busy_tables(stage: Stage) -> None:
    await stage.configure(True, "least_loaded")
    await stage.bulk(["T2", "T3"], [stage.w1])
    await stage.bulk(["B1"], [stage.w2])
    await stage.bulk(["B2"], [stage.w3])
    for label in ("T2", "T3", "B1"):
        await stage.guest_orders(label)
    await stage.guest_orders("T1")  # w3 has no busy table, w2 one, w1 two
    assert await stage.waiters_of("T1") == {str(stage.w3)}


async def test_rotation_takes_turns_and_the_cursor_is_saved(stage: Stage) -> None:
    await stage.configure(True, "rotation")
    order = sorted([str(stage.w1), str(stage.w2), str(stage.w3)])
    picked = []
    for label in ("T1", "T2", "T3", "B1"):
        await stage.guest_orders(label)
        (who,) = await stage.waiters_of(label)
        picked.append(who)
    assert picked == [order[0], order[1], order[2], order[0]]
    async with stage.engine.connect() as conn:
        cursor = await conn.scalar(
            text("SELECT assignment_rotation_last_user_id FROM outlet WHERE id = :o"),
            {"o": stage.seed.outlet_a},
        )
    assert str(cursor) == order[0]


async def test_nearest_prefers_the_waiter_already_in_the_zone(stage: Stage) -> None:
    await stage.configure(True, "nearest")
    await stage.bulk(["T2"], [stage.w1])
    await stage.bulk(["B1"], [stage.w2])
    await stage.guest_orders("B2")  # bar zone: w2 is there
    assert await stage.waiters_of("B2") == {str(stage.w2)}
    await stage.guest_orders("T1")  # floor zone: w1 is there
    assert await stage.waiters_of("T1") == {str(stage.w1)}


async def test_nearest_falls_back_to_least_loaded_when_nobody_serves_the_zone(stage: Stage) -> None:
    await stage.configure(True, "nearest")
    await stage.bulk(["T2", "T3"], [stage.w1])
    await stage.bulk(["T1"], [stage.w2])
    await stage.guest_orders("T2")
    await stage.guest_orders("T3")
    await stage.guest_orders("T1")
    await stage.guest_orders("B1")  # nobody in bar: w3 has the lightest load
    assert await stage.waiters_of("B1") == {str(stage.w3)}


async def test_the_waiter_sees_the_table_and_the_event_log_says_who_was_picked(
    stage: Stage,
) -> None:
    await stage.configure(True, "rotation")
    guest = await stage.guest_orders("T1")
    (who,) = await stage.waiters_of("T1")
    token = stage.seed.token(uuid.UUID(who), Role.WAITER) if who == str(stage.w1) else None
    if token:
        mine = (await stage.client.get(f"{floor(stage.seed)}/table-map", headers=hdr(token))).json()
        assert [t["label"] for t in mine["tables"]] == ["T1"]
    log = await events(stage.engine, guest.tab_id)
    assert ("waiter_assigned", "system") in log
    async with stage.engine.connect() as conn:
        payload = (
            await conn.execute(
                text(
                    "SELECT payload FROM tab_event WHERE tab_id = :t AND event = 'waiter_assigned'"
                ),
                {"t": uuid.UUID(guest.tab_id)},
            )
        ).scalar_one()
    assert (
        payload["strategy"] == "rotation" and payload["auto"] is True and payload["user_id"] == who
    )


async def test_only_active_waiters_are_eligible_and_none_means_unassigned_not_lost(
    stage: Stage, owner_engine: AsyncEngine
) -> None:
    await stage.configure(True, "least_loaded")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE staff_role SET active = false WHERE user_id = ANY(:u)"),
            {"u": [stage.w1, stage.w2, stage.w3]},
        )
    guest = await new_guest(stage.client, stage.seed, "T1")
    placed = await guest.order([one(stage.menu.item)])
    assert placed.status_code == 201  # the order is placed regardless
    card = await stage.card("T1")
    assert card["waiters"] == [] and card["needs_waiter"] is True
    assert len(card["waiting_orders"]) == 1

    async with owner_engine.begin() as conn:  # one comes back: only that one can be chosen
        await conn.execute(
            text("UPDATE staff_role SET active = true WHERE user_id = :u"), {"u": stage.w3}
        )
    await stage.guest_orders("T2")
    assert await stage.waiters_of("T2") == {str(stage.w3)}
    # The earlier order's table is still waiting; a further order there picks it up.
    await guest.order([one(stage.menu.item)])
    assert await stage.waiters_of("T1") == {str(stage.w3)}


async def test_an_automatic_assignment_ends_with_the_guest_and_manual_ones_stay(
    stage: Stage, owner_engine: AsyncEngine
) -> None:
    await stage.configure(True, "rotation")
    order = sorted([str(stage.w1), str(stage.w2), str(stage.w3)])
    first = await stage.guest_orders("T1")
    assert await stage.waiters_of("T1") == {order[0]}
    await stage.bulk(["T2"], [stage.w1])  # manual: must survive

    async with owner_engine.begin() as conn:  # the guest leaves
        await conn.execute(
            text("UPDATE tab SET status = 'closed', closed_at = now() WHERE id = :t"),
            {"t": uuid.UUID(first.tab_id)},
        )
    await stage.guest_orders("T1")  # the next guest is balanced afresh: the turn moves on
    assert await stage.waiters_of("T1") == {order[1]}
    assert await stage.waiters_of("T2") == {str(stage.w1)}


async def test_transferring_a_tab_releases_the_automatic_assignment_left_behind(
    stage: Stage,
) -> None:
    await stage.configure(True, "rotation")
    guest = await stage.guest_orders("T1")
    assert (await stage.card("T1"))["auto_assigned"] is True
    r = await stage.client.post(
        f"{floor(stage.seed)}/tabs/{guest.tab_id}/transfer",
        json={"table_id": await stage.table_id("T3")},
        headers=manager(stage.seed),
    )
    assert r.status_code == 200, r.text
    assert await stage.waiters_of("T1") == set()


async def test_concurrent_orders_are_distributed_not_piled_on_one_waiter(stage: Stage) -> None:
    await stage.configure(True, "least_loaded")
    guests = [await new_guest(stage.client, stage.seed, label) for label in ("T1", "T2", "T3")]
    results = await asyncio.gather(*(g.order([one(stage.menu.item)]) for g in guests))
    assert [r.status_code for r in results] == [201, 201, 201], [r.text for r in results]
    picked = [next(iter(await stage.waiters_of(label))) for label in ("T1", "T2", "T3")]
    assert len(set(picked)) == 3  # three tables, three waiters, no double booking


async def test_concurrent_rotation_never_gives_two_orders_the_same_turn(stage: Stage) -> None:
    await stage.configure(True, "rotation")
    guests = [
        await new_guest(stage.client, stage.seed, label) for label in ("T1", "T2", "T3", "B1")
    ]
    results = await asyncio.gather(*(g.order([one(stage.menu.item)]) for g in guests))
    assert all(r.status_code == 201 for r in results)
    picked = [next(iter(await stage.waiters_of(label))) for label in ("T1", "T2", "T3", "B1")]
    counts = sorted(picked.count(u) for u in set(picked))
    assert counts == [1, 1, 2]  # 4 orders over 3 waiters: turns were taken one at a time
