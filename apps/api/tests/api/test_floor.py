"""The waiter's floor: table map, walk-ins, adding items, guest acknowledgement,
serving, transfer, merge and the requests feed."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.permissions import Role
from tests.api.guest_helpers import (
    FakeClock,
    Guest,
    assign,
    events,
    floor,
    kitchen,
    manager,
    new_guest,
    one,
    scan,
    staff,
    table_token,
    waiter,
)
from tests.api.helpers import Menu
from tests.conftest import Seed, hdr


def item_line(menu: Menu, qty: int = 1) -> dict[str, Any]:
    return {"menu_item_id": menu.item["id"], "qty": qty}


async def staff_order(
    client: httpx.AsyncClient,
    seed: Seed,
    tab_id: str,
    lines: list[dict[str, Any]],
    who: dict[str, str] | None = None,
    key: uuid.UUID | None = None,
) -> httpx.Response:
    headers = dict(who or waiter(seed))
    if key:
        headers["Idempotency-Key"] = str(key)
    return await client.post(
        f"{floor(seed)}/tabs/{tab_id}/orders", json={"lines": lines}, headers=headers
    )


async def walk_in(client: httpx.AsyncClient, seed: Seed, table_id: uuid.UUID) -> str:
    r = await client.post(f"{floor(seed)}/tables/{table_id}/tab", json={}, headers=waiter(seed))
    assert r.status_code == 200, r.text
    return str(r.json()["tab_id"])


async def card(client: httpx.AsyncClient, seed: Seed, label: str) -> dict[str, Any]:
    rows = (await client.get(f"{floor(seed)}/table-map", headers=manager(seed))).json()["tables"]
    return dict(next(t for t in rows if t["label"] == label))


# --- table map -----------------------------------------------------------------


async def test_table_colours_follow_the_visit(
    client: httpx.AsyncClient, seed: Seed, env: Menu, fake_clock: FakeClock
) -> None:
    assert (await card(client, seed, "T1"))["state"] == "empty"

    g = await new_guest(client, seed, "T1")
    seated = await card(client, seed, "T1")
    assert (seated["state"], seated["tab_id"], seated["opened_by"]) == (
        "seated",
        g.tab_id,
        "customer",
    )

    await g.order([one(env.item, 1)])
    pending = await card(client, seed, "T1")
    assert (pending["state"], pending["pending_rounds"]) == ("order_pending", 1)
    assert pending["estimated_total_paise"] == 32000

    await client.post(f"{g.base}/service-requests", json={"type": "water"}, headers=g.headers())
    assert (await card(client, seed, "T1"))["open_requests"] == ["water"]

    await client.post(f"{g.base}/service-requests", json={"type": "bill"}, headers=g.headers())
    assert (await card(client, seed, "T1"))["state"] == "bill_requested"


async def test_the_map_shows_who_serves_a_table_and_a_walk_ins_total(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    table_id = await assign(owner_engine, seed, "T1")
    patched = await client.patch(
        f"/v1/outlets/{seed.outlet_a}/settings",
        json={"service_charge_bp": 1000},
        headers=staff(seed, seed.owner_a, Role.OWNER),
    )
    assert patched.status_code == 200
    tab_id = await walk_in(client, seed, table_id)
    await staff_order(client, seed, tab_id, [item_line(env, 2)])
    mine = next(
        t
        for t in (await client.get(f"{floor(seed)}/table-map", headers=waiter(seed))).json()[
            "tables"
        ]
    )
    assert mine["waiters"] and mine["awaiting_confirm"] is False
    assert mine["estimated_total_paise"] == 64000 + 6095  # items plus 10% service charge estimate
    assert mine["awaiting_ack"] == 0 and mine["disputes"] == 0


async def test_the_map_is_forbidden_to_the_kitchen_and_other_tenants(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    assert (await client.get(f"{floor(seed)}/table-map", headers=kitchen(seed))).status_code == 403
    assert (await client.get(f"{floor(seed)}/table-map")).status_code == 401
    outsider = hdr(seed.token(seed.manager_b, Role.MANAGER, tenant="b"))
    assert (await client.get(f"{floor(seed)}/table-map", headers=outsider)).status_code == 403


# --- walk-ins ------------------------------------------------------------------


async def test_a_waiter_opens_a_walk_in_tab_without_a_phone(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    table_id = await assign(owner_engine, seed, "T1")
    key = uuid.uuid4()
    headers = {**waiter(seed), "Idempotency-Key": str(key)}
    first = await client.post(
        f"{floor(seed)}/tables/{table_id}/tab", json={"guest_count": 4}, headers=headers
    )
    replay = await client.post(
        f"{floor(seed)}/tables/{table_id}/tab", json={"guest_count": 4}, headers=headers
    )
    assert first.json() == replay.json() and first.json()["created"] is True
    again = await client.post(f"{floor(seed)}/tables/{table_id}/tab", json={}, headers=waiter(seed))
    assert again.json() == {"tab_id": first.json()["tab_id"], "created": False}

    view = (
        await client.get(f"{floor(seed)}/tabs/{first.json()['tab_id']}", headers=waiter(seed))
    ).json()
    assert (view["opened_by"], view["guest_sessions"]) == ("waiter", 0)
    assert view["tab"]["awaiting_waiter"] is False
    log = await events(owner_engine, first.json()["tab_id"])
    assert log == [("opened", "staff")]


async def test_walk_in_rules(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    t1 = await assign(owner_engine, seed, "T1")
    t2 = uuid.UUID(
        next(
            t
            for t in (await client.get(f"{floor(seed)}/table-map", headers=manager(seed))).json()[
                "tables"
            ]
            if t["label"] == "T2"
        )["id"]
    )
    # Not their table: 404. Unknown table: 404. The kitchen may not open tabs.
    assert (
        await client.post(f"{floor(seed)}/tables/{t2}/tab", json={}, headers=waiter(seed))
    ).status_code == 404
    assert (
        await client.post(
            f"{floor(seed)}/tables/{uuid.uuid4()}/tab", json={}, headers=manager(seed)
        )
    ).status_code == 404
    assert (
        await client.post(f"{floor(seed)}/tables/{t1}/tab", json={}, headers=kitchen(seed))
    ).status_code == 403
    assert (
        await client.post(
            f"{floor(seed)}/tables/{t1}/tab", json={"guest_count": 0}, headers=waiter(seed)
        )
    ).status_code == 422
    # A table a guest is already at returns that tab.
    guest = await new_guest(client, seed, "T1")
    r = await client.post(f"{floor(seed)}/tables/{t1}/tab", json={}, headers=waiter(seed))
    assert r.json() == {"tab_id": guest.tab_id, "created": False}
    # Inactive tables can't be opened.
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE dining_table SET active = false WHERE id = :t"), {"t": t1})
    assert (
        await client.post(f"{floor(seed)}/tables/{t1}/tab", json={}, headers=manager(seed))
    ).status_code == 404


# --- adding items for a guest ----------------------------------------------------


async def test_a_waiter_adds_a_round_that_is_accepted_at_once_and_names_them(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await assign(owner_engine, seed, "T1")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE app_user SET name = 'Ravi' WHERE id = :u"), {"u": seed.waiter_a}
        )
    g = await new_guest(client, seed, "T1")
    r = await staff_order(client, seed, g.tab_id, [item_line(env, 1)])
    assert r.status_code == 201, r.text
    rnd = r.json()
    assert (rnd["status"], rnd["undo_until"]) == ("accepted", None)
    line = rnd["lines"][0]
    assert (line["placed_by"], line["staff_name"], line["by_you"]) == ("staff", "Ravi", False)
    assert line["needs_customer_ack"] is False and line["ack_state"] == "not_needed"

    guest_view = (await g.tab())["rounds"][0]["lines"][0]
    assert guest_view["staff_name"] == "Ravi" and guest_view["by_you"] is False
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE app_user SET name = NULL WHERE id = :u"), {"u": seed.waiter_a}
        )
        source, staff_user = (
            await conn.execute(
                text(
                    "SELECT o.source, l.staff_user_id FROM tab_order o JOIN order_line l ON l.order_id = o.id WHERE o.tab_id = :t"
                ),
                {"t": uuid.UUID(g.tab_id)},
            )
        ).one()
    assert (source, staff_user) == ("waiter", seed.waiter_a)


async def test_lines_at_or_above_the_threshold_ask_the_guest_unless_nobody_can_answer(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    t1 = await assign(owner_engine, seed, "T1")
    t2 = await assign(owner_engine, seed, "T2")
    # T1 has a guest phone on it: a 640.00 line needs their OK; a 320.00 line does not.
    g = await new_guest(client, seed, "T1")
    big = (await staff_order(client, seed, g.tab_id, [item_line(env, 2)])).json()["lines"][0]
    small = (await staff_order(client, seed, g.tab_id, [item_line(env, 1)])).json()["lines"][0]
    assert (big["needs_customer_ack"], big["ack_state"]) == (True, "awaiting")
    assert (small["needs_customer_ack"], small["ack_state"]) == (False, "not_needed")

    # T2 is a walk-in with nobody to ask: the requirement is waived and logged, not dropped.
    walk = await walk_in(client, seed, t2)
    waived = (await staff_order(client, seed, walk, [item_line(env, 2)])).json()["lines"][0]
    assert waived["needs_customer_ack"] is False
    async with owner_engine.connect() as conn:
        payloads = [
            r[0]
            for r in await conn.execute(
                text("SELECT payload FROM tab_event WHERE tab_id = :t AND event = 'line_added'"),
                {"t": uuid.UUID(walk)},
            )
        ]
    assert payloads[0]["ack_waived"] is True and payloads[0]["needs_customer_ack"] is False
    async with owner_engine.connect() as conn:
        asked = [
            r[0]
            for r in await conn.execute(
                text(
                    "SELECT payload FROM tab_event WHERE tab_id = :t AND event = 'line_added' ORDER BY id"
                ),
                {"t": uuid.UUID(g.tab_id)},
            )
        ]
    assert asked[0]["needs_customer_ack"] is True and "ack_waived" not in asked[0]
    del t1


async def test_a_guest_scanning_later_can_be_asked_about_new_lines(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    t1 = await assign(owner_engine, seed, "T1")
    walk = await walk_in(client, seed, t1)
    await staff_order(client, seed, walk, [item_line(env, 2)])
    guest = await scan(client, await table_token(client, seed, "T1"))
    assert guest.json()["tab_id"] == walk  # the guest joins the waiter's tab
    later = (await staff_order(client, seed, walk, [item_line(env, 2)])).json()["lines"][0]
    assert later["needs_customer_ack"] is True


async def test_adding_items_is_role_and_tab_checked(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await assign(owner_engine, seed, "T1")
    g = await new_guest(client, seed, "T1")
    assert (
        await staff_order(client, seed, g.tab_id, [item_line(env)], kitchen(seed))
    ).status_code == 403
    assert (
        await client.post(f"{floor(seed)}/tabs/{g.tab_id}/orders", json={"lines": [item_line(env)]})
    ).status_code == 401
    guest_token_as_staff = await client.post(
        f"{floor(seed)}/tabs/{g.tab_id}/orders",
        json={"lines": [item_line(env)]},
        headers=hdr(g.token),
    )
    assert guest_token_as_staff.status_code == 401
    unknown = await staff_order(
        client, seed, g.tab_id, [{"menu_item_id": str(uuid.uuid4()), "qty": 1}]
    )
    assert (unknown.status_code, unknown.json()["code"]) == (422, "unknown_item")
    assert (
        await staff_order(client, seed, str(uuid.uuid4()), [item_line(env)], manager(seed))
    ).status_code == 404
    other = hdr(seed.token(seed.manager_b, Role.MANAGER, tenant="b"))
    assert (await staff_order(client, seed, g.tab_id, [item_line(env)], other)).status_code == 403
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE tab SET status = 'closed' WHERE id = :t"), {"t": uuid.UUID(g.tab_id)}
        )
    closed = await staff_order(client, seed, g.tab_id, [item_line(env)], manager(seed))
    assert (closed.status_code, closed.json()["code"]) == (409, "tab_not_open")


async def test_a_replayed_staff_order_places_one_round(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await assign(owner_engine, seed, "T1")
    g = await new_guest(client, seed, "T1")
    key = uuid.uuid4()
    results = await asyncio.gather(
        *(staff_order(client, seed, g.tab_id, [item_line(env)], key=key) for _ in range(4))
    )
    ok = [r for r in results if r.status_code == 201]
    assert ok and len({r.json()["id"] for r in ok}) == 1
    assert len((await g.tab())["rounds"]) == 1


async def test_a_waiter_attending_an_unconfirmed_table_confirms_it(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await client.patch(
        f"/v1/outlets/{seed.outlet_a}/settings",
        json={"waiter_confirm_mode": True},
        headers=staff(seed, seed.owner_a, Role.OWNER),
    )
    await assign(owner_engine, seed, "T1")
    g = await new_guest(client, seed, "T1")
    assert (await g.tab())["awaiting_waiter"] is True
    assert (await staff_order(client, seed, g.tab_id, [item_line(env)])).status_code == 201
    assert (await g.tab())["awaiting_waiter"] is False
    log = [e for e, _ in await events(owner_engine, g.tab_id)]
    assert log.count("confirmed") == 1


async def test_liquor_needing_approval_is_a_managers_call(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    owner = staff(seed, seed.owner_a, Role.OWNER)
    await client.patch(
        f"/v1/outlets/{seed.outlet_a}/settings",
        json={
            "liquor_licensed": True,
            "liquor_vat_rate_bp": 2000,
            "liquor_approval_required": True,
        },
        headers=owner,
    )
    whisky = (
        await client.post(
            f"{env.base}/items",
            json={
                "category_id": env.category["id"],
                "name": "G Whisky",
                "base_price_paise": 40000,
                "tax_class_id": env.tax_liquor["id"],
                "is_liquor": True,
                "needs_approval": True,
            },
            headers=owner,
        )
    ).json()
    await assign(owner_engine, seed, "T1")
    g = await new_guest(client, seed, "T1")
    by_waiter = await staff_order(
        client, seed, g.tab_id, [{"menu_item_id": whisky["id"], "qty": 1}]
    )
    assert (by_waiter.status_code, by_waiter.json()["code"]) == (409, "needs_manager")
    by_manager = await staff_order(
        client, seed, g.tab_id, [{"menu_item_id": whisky["id"], "qty": 1}], manager(seed)
    )
    assert by_manager.status_code == 201, by_manager.text


# --- guest acknowledgement -------------------------------------------------------


async def _awaiting_line(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> tuple[Guest, dict[str, Any]]:
    await assign(owner_engine, seed, "T1")
    g = await new_guest(client, seed, "T1")
    line = (await staff_order(client, seed, g.tab_id, [item_line(env, 2)])).json()["lines"][0]
    return g, line


async def test_the_guest_can_confirm_a_staff_added_line(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    g, line = await _awaiting_line(client, seed, env, owner_engine)
    r = await client.post(
        f"{g.base}/lines/{line['id']}/ack", json={"answer": "ours"}, headers=g.headers()
    )
    assert r.status_code == 200 and r.json()["ack_state"] == "acked" and r.json()["acked_at"]
    again = await client.post(
        f"{g.base}/lines/{line['id']}/ack", json={"answer": "not_ours"}, headers=g.headers()
    )
    assert (again.status_code, again.json()["code"]) == (409, "already_answered")
    assert "line_acked" in [e for e, _ in await events(owner_engine, g.tab_id)]
    alerts = (await client.get(f"{floor(seed)}/alerts", headers=manager(seed))).json()
    assert alerts == []


async def test_not_ours_raises_a_manager_alert_and_leaves_the_line_in_place(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    g, line = await _awaiting_line(client, seed, env, owner_engine)
    r = await client.post(
        f"{g.base}/lines/{line['id']}/ack", json={"answer": "not_ours"}, headers=g.headers()
    )
    assert r.json()["ack_state"] == "disputed"
    tab = await g.tab()
    assert (
        tab["rounds"][0]["lines"][0]["status"] == "accepted"
    )  # still on the tab and in the kitchen
    assert tab["totals"]["items_paise"] == 64000

    alerts = (await client.get(f"{floor(seed)}/alerts", headers=manager(seed))).json()
    assert len(alerts) == 1
    assert (alerts[0]["kind"], alerts[0]["table_label"], alerts[0]["item"]) == (
        "line_disputed",
        "T1",
        "G Paneer Tikka",
    )
    assert (await card(client, seed, "T1"))["disputes"] == 1
    assert (await client.get(f"{floor(seed)}/alerts", headers=waiter(seed))).status_code == 403
    assert (await client.get(f"{floor(seed)}/alerts", headers=kitchen(seed))).status_code == 403
    outsider = hdr(seed.token(seed.manager_b, Role.MANAGER, tenant="b"))
    assert (await client.get(f"{floor(seed)}/alerts", headers=outsider)).status_code == 403
    assert "line_disputed" in [e for e, _ in await events(owner_engine, g.tab_id)]


async def test_an_unanswered_line_becomes_an_alert_after_three_minutes(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    owner_engine: AsyncEngine,
    fake_clock: FakeClock,
) -> None:
    g, _ = await _awaiting_line(client, seed, env, owner_engine)
    assert (await client.get(f"{floor(seed)}/alerts", headers=manager(seed))).json() == []
    assert (await card(client, seed, "T1"))["awaiting_ack"] == 1
    fake_clock.advance(181)
    alerts = (await client.get(f"{floor(seed)}/alerts", headers=manager(seed))).json()
    assert [a["kind"] for a in alerts] == ["ack_pending"]
    del g


async def test_ack_is_only_for_the_guests_own_staff_added_lines(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    g, line = await _awaiting_line(client, seed, env, owner_engine)
    mine = (await g.order([one(env.item)])).json()["lines"][0]
    r = await client.post(
        f"{g.base}/lines/{mine['id']}/ack", json={"answer": "ours"}, headers=g.headers()
    )
    assert (r.status_code, r.json()["code"]) == (409, "no_ack_needed")
    assert (
        await client.post(
            f"{g.base}/lines/{uuid.uuid4()}/ack", json={"answer": "ours"}, headers=g.headers()
        )
    ).status_code == 404
    other = await new_guest(client, seed, "T2")
    cross = await client.post(
        f"{other.base}/lines/{line['id']}/ack", json={"answer": "ours"}, headers=other.headers()
    )
    assert cross.status_code == 404
    wrong_tab = await client.post(
        f"{g.base.rsplit('/', 1)[0]}/{other.tab_id}/lines/{line['id']}/ack",
        json={"answer": "ours"},
        headers=g.headers(),
    )
    assert wrong_tab.status_code == 403
    bad = await client.post(
        f"{g.base}/lines/{line['id']}/ack", json={"answer": "maybe"}, headers=g.headers()
    )
    assert bad.status_code == 422


# --- transfer and merge ---------------------------------------------------------


async def test_a_tab_moves_to_a_free_table_and_the_guest_stays_on_it(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await assign(owner_engine, seed, "T1")
    t2 = await assign(owner_engine, seed, "T2")
    g = await new_guest(client, seed, "T1")
    await g.order([one(env.item)])
    r = await client.post(
        f"{floor(seed)}/tabs/{g.tab_id}/transfer", json={"table_id": str(t2)}, headers=waiter(seed)
    )
    assert r.status_code == 200, r.text
    assert r.json()["table_id"] == str(t2) and r.json()["tab"]["table_label"] == "T2"
    assert (await g.tab())["table_label"] == "T2"  # the guest's session is unaffected
    assert (await card(client, seed, "T1"))["state"] == "empty"
    assert (await card(client, seed, "T2"))["tab_id"] == g.tab_id
    log = await events(owner_engine, g.tab_id)
    assert "transferred" in [e for e, _ in log]
    # T1 is free again for a new party.
    assert (await scan(client, await table_token(client, seed, "T1"))).json()["tab_id"] != g.tab_id


async def test_transfer_refusals(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await assign(owner_engine, seed, "T1")
    t2 = await assign(owner_engine, seed, "T2")
    a = await new_guest(client, seed, "T1")
    b = await new_guest(client, seed, "T2")
    url = f"{floor(seed)}/tabs/{a.tab_id}/transfer"
    occupied = await client.post(url, json={"table_id": str(t2)}, headers=waiter(seed))
    assert (occupied.status_code, occupied.json()["code"]) == (409, "table_occupied")
    assert occupied.json()["details"] == {"tab_id": b.tab_id}
    t1 = uuid.UUID((await card(client, seed, "T1"))["id"])
    same = await client.post(url, json={"table_id": str(t1)}, headers=waiter(seed))
    assert (same.status_code, same.json()["code"]) == (409, "same_table")
    assert (
        await client.post(url, json={"table_id": str(uuid.uuid4())}, headers=waiter(seed))
    ).status_code == 404
    assert (
        await client.post(url, json={"table_id": str(t2)}, headers=kitchen(seed))
    ).status_code == 403
    # A waiter may not send a tab to a table that isn't theirs.
    async with owner_engine.begin() as conn:
        await conn.execute(text("DELETE FROM table_assignment WHERE table_id = :t"), {"t": t2})
        await conn.execute(
            text("UPDATE tab SET status = 'closed' WHERE id = :t"), {"t": uuid.UUID(b.tab_id)}
        )
    assert (
        await client.post(url, json={"table_id": str(t2)}, headers=waiter(seed))
    ).status_code == 404
    assert (
        await client.post(url, json={"table_id": str(t2)}, headers=manager(seed))
    ).status_code == 200


async def test_merging_moves_everything_and_the_guests_follow(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    owner_engine: AsyncEngine,
    fake_clock: FakeClock,
) -> None:
    await assign(owner_engine, seed, "T1")
    await assign(owner_engine, seed, "T2")
    a = await new_guest(client, seed, "T1")  # will be merged into b
    b = await new_guest(client, seed, "T2")
    await b.order([one(env.item)])
    fake_clock.advance(5)
    await a.order([one(env.item, 2)])
    await staff_order(client, seed, a.tab_id, [item_line(env, 3)])
    await client.post(f"{a.base}/service-requests", json={"type": "water"}, headers=a.headers())
    await client.post(f"{b.base}/service-requests", json={"type": "water"}, headers=b.headers())

    r = await client.post(
        f"{floor(seed)}/tabs/{a.tab_id}/merge", json={"into_tab_id": b.tab_id}, headers=waiter(seed)
    )
    assert r.status_code == 200, r.text
    merged = r.json()["tab"]
    assert merged["id"] == b.tab_id
    assert [(rnd["seq_no"], rnd["lines"][0]["qty"]) for rnd in merged["rounds"]] == [
        (1, 1),
        (2, 2),
        (3, 3),
    ]
    assert merged["totals"]["items_paise"] == 32000 * 6
    assert merged["open_requests"] == ["water"]  # the duplicate request was closed, not doubled
    assert r.json()["guest_sessions"] == 2

    # Both phones are on the merged tab; the old tab id no longer works for them.
    for guest in (a, b):
        session = (
            await client.get(
                f"/v1/outlets/{guest.outlet_id}/guest/session", headers=guest.headers()
            )
        ).json()
        assert session["tab_id"] == b.tab_id and session["table_label"] == "T2"
        assert (
            len(
                (
                    await client.get(
                        f"/v1/outlets/{guest.outlet_id}/tabs/{b.tab_id}", headers=guest.headers()
                    )
                ).json()["rounds"]
            )
            == 3
        )
    stale = await client.get(a.base, headers=a.headers())
    assert (stale.status_code, stale.json()["code"]) == (403, "permission_denied")

    assert (await card(client, seed, "T1"))["state"] == "empty"
    async with owner_engine.connect() as conn:
        status = await conn.scalar(
            text("SELECT status FROM tab WHERE id = :t"), {"t": uuid.UUID(a.tab_id)}
        )
        lines_left = await conn.scalar(
            text("SELECT count(*) FROM order_line WHERE tab_id = :t"), {"t": uuid.UUID(a.tab_id)}
        )
    assert (status, lines_left) == ("voided", 0)
    for tab in (a.tab_id, b.tab_id):
        assert "merged" in [e for e, _ in await events(owner_engine, tab)]


async def test_merge_refusals(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await assign(owner_engine, seed, "T1")
    a = await new_guest(client, seed, "T1")
    b = await new_guest(client, seed, "T2")
    url = f"{floor(seed)}/tabs/{a.tab_id}/merge"
    same = await client.post(url, json={"into_tab_id": a.tab_id}, headers=manager(seed))
    assert (same.status_code, same.json()["code"]) == (409, "same_tab")
    assert (
        await client.post(url, json={"into_tab_id": str(uuid.uuid4())}, headers=manager(seed))
    ).status_code == 404
    # T2 isn't the waiter's table.
    assert (
        await client.post(url, json={"into_tab_id": b.tab_id}, headers=waiter(seed))
    ).status_code == 404
    assert (
        await client.post(url, json={"into_tab_id": b.tab_id}, headers=kitchen(seed))
    ).status_code == 403
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE tab SET status = 'closed' WHERE id = :t"), {"t": uuid.UUID(b.tab_id)}
        )
    closed = await client.post(url, json={"into_tab_id": b.tab_id}, headers=manager(seed))
    assert (closed.status_code, closed.json()["code"]) == (409, "tab_not_open")


async def test_a_bill_requested_tab_can_be_merged_away(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    a = await new_guest(client, seed, "T1")
    b = await new_guest(client, seed, "T2")
    await a.order([one(env.item)])
    await client.post(f"{a.base}/service-requests", json={"type": "bill"}, headers=a.headers())
    r = await client.post(
        f"{floor(seed)}/tabs/{a.tab_id}/merge",
        json={"into_tab_id": b.tab_id},
        headers=manager(seed),
    )
    assert r.status_code == 200
    assert r.json()["tab"]["open_requests"] == ["bill"]


async def test_opposite_merges_at_once_never_deadlock(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    a = await new_guest(client, seed, "T1")
    b = await new_guest(client, seed, "T2")
    results = await asyncio.gather(
        client.post(
            f"{floor(seed)}/tabs/{a.tab_id}/merge",
            json={"into_tab_id": b.tab_id},
            headers=manager(seed),
        ),
        client.post(
            f"{floor(seed)}/tabs/{b.tab_id}/merge",
            json={"into_tab_id": a.tab_id},
            headers=manager(seed),
        ),
    )
    assert sorted(r.status_code for r in results) == [200, 409]


# --- requests feed -------------------------------------------------------------


async def test_the_requests_feed_is_scoped_and_resolvable(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await assign(owner_engine, seed, "T1")
    mine = await new_guest(client, seed, "T1")
    theirs = await new_guest(client, seed, "T2")
    for g, kind in ((mine, "waiter"), (theirs, "water")):
        await client.post(f"{g.base}/service-requests", json={"type": kind}, headers=g.headers())

    feed = (await client.get(f"{floor(seed)}/service-requests", headers=waiter(seed))).json()
    assert [(r["type"], r["table_label"]) for r in feed] == [("waiter", "T1")]
    everything = (await client.get(f"{floor(seed)}/service-requests", headers=manager(seed))).json()
    assert {r["type"] for r in everything} == {"waiter", "water"}

    request_id = feed[0]["id"]
    assert (
        await client.post(
            f"{floor(seed)}/service-requests/{everything[1]['id']}/resolve", headers=waiter(seed)
        )
    ).status_code == 404
    assert (
        await client.post(
            f"{floor(seed)}/service-requests/{request_id}/resolve", headers=kitchen(seed)
        )
    ).status_code == 403
    done = await client.post(
        f"{floor(seed)}/service-requests/{request_id}/resolve", headers=waiter(seed)
    )
    assert done.status_code == 200
    again = await client.post(
        f"{floor(seed)}/service-requests/{request_id}/resolve", headers=waiter(seed)
    )
    assert again.status_code == 200
    assert (await client.get(f"{floor(seed)}/service-requests", headers=waiter(seed))).json() == []
    assert (await mine.tab())["open_requests"] == []
    log = [e for e, _ in await events(owner_engine, mine.tab_id)]
    assert log.count("service_request_resolved") == 1
    assert (
        await client.post(
            f"{floor(seed)}/service-requests/{uuid.uuid4()}/resolve", headers=manager(seed)
        )
    ).status_code == 404


async def test_the_staff_menu_is_what_the_guest_sees(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    r = await client.get(
        f"{floor(seed)}/staff-menu".replace("staff-menu", "menu"), headers=waiter(seed)
    )
    assert r.status_code == 200
    names = [i["name"] for c in r.json()["categories"] for i in c["items"]]
    assert "G Paneer Tikka" in names
    assert (await client.get(f"{floor(seed)}/menu", headers=kitchen(seed))).status_code == 403
