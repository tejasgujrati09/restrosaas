"""Tickets: the kitchen and bar queue, the undo-window lock, serving, and sold out."""

from __future__ import annotations

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
    staff,
    waiter,
)
from tests.api.helpers import Menu
from tests.conftest import Seed, hdr


def base(seed: Seed) -> str:
    return f"/v1/outlets/{seed.outlet_a}"


async def queue(
    client: httpx.AsyncClient, seed: Seed, who: dict[str, str] | None = None, **params: str
) -> dict[str, Any]:
    r = await client.get(f"{base(seed)}/tickets", params=params, headers=who or kitchen(seed))
    assert r.status_code == 200, r.text
    return dict(r.json())


async def act(
    client: httpx.AsyncClient,
    seed: Seed,
    ticket_id: str,
    verb: str,
    who: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        f"{base(seed)}/tickets/{ticket_id}/{verb}", headers=who or kitchen(seed)
    )


async def order_lines(engine: AsyncEngine, order_id: str) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT status FROM order_line WHERE order_id = :o ORDER BY id"),
            {"o": uuid.UUID(order_id)},
        )
        return [r[0] for r in rows]


async def order_status(engine: AsyncEngine, order_id: str) -> str:
    async with engine.connect() as conn:
        return str(
            await conn.scalar(
                text("SELECT status FROM tab_order WHERE id = :o"), {"o": uuid.UUID(order_id)}
            )
        )


async def serve(
    client: httpx.AsyncClient,
    seed: Seed,
    g: Guest,
    order_id: str,
    body: dict[str, Any] | None = None,
    who: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        f"{floor(seed)}/tabs/{g.tab_id}/orders/{order_id}/serve",
        json=body or {},
        headers=who or waiter(seed),
    )


# --- the undo-window lock --------------------------------------------------------


async def test_a_ticket_shows_at_once_but_cannot_start_until_the_undo_window_closes(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item, 2, note="less oil")])).json()

    q = (await queue(client, seed))["queue"]
    assert len(q) == 1
    ticket = q[0]
    assert (ticket["status"], ticket["can_start"], ticket["table_label"]) == ("queued", False, "T1")
    assert ticket["holding_until"].startswith("2026-09-18T13:31:00")  # placed + 60 s
    assert ticket["lines"] == [
        {
            "name": "G Paneer Tikka",
            "qty": 2,
            "modifiers": [],
            "note": "less oil",
            "status": "placed",
        }
    ]
    assert "price" not in str(ticket)

    early = await act(client, seed, ticket["id"], "start")
    assert (early.status_code, early.json()["code"]) == (409, "undo_window_open")

    fake_clock.advance(61)
    started = await act(client, seed, ticket["id"], "start")
    assert started.status_code == 200, started.text
    assert (started.json()["status"], started.json()["holding_until"]) == ("preparing", None)
    assert await order_status(owner_engine, placed["id"]) == "preparing"
    assert await order_lines(owner_engine, placed["id"]) == ["preparing"]


async def test_the_queue_itself_accepts_rounds_whose_window_has_closed(
    client: httpx.AsyncClient, seed: Seed, env: Menu, fake_clock: FakeClock
) -> None:
    g = await new_guest(client, seed)
    await g.order([one(env.item)])
    assert (await queue(client, seed))["queue"][0]["can_start"] is False
    fake_clock.advance(61)
    assert (await queue(client, seed))["queue"][0]["can_start"] is True


async def test_undoing_a_round_removes_its_ticket(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item)])).json()
    assert len((await queue(client, seed))["queue"]) == 1
    await client.post(f"{g.base}/orders/{placed['id']}/undo", headers=g.headers())
    assert (await queue(client, seed))["queue"] == []


async def test_a_waiters_round_is_startable_immediately(
    client: httpx.AsyncClient, seed: Seed, env: Menu, owner_engine: AsyncEngine
) -> None:
    await assign(owner_engine, seed, "T1")
    g = await new_guest(client, seed)
    r = await client.post(
        f"{floor(seed)}/tabs/{g.tab_id}/orders",
        json={"lines": [{"menu_item_id": env.item["id"], "qty": 1}]},
        headers=waiter(seed),
    )
    ticket = (await queue(client, seed))["queue"][0]
    assert (ticket["can_start"], ticket["holding_until"]) == (True, None)
    assert (await act(client, seed, ticket["id"], "start")).status_code == 200
    assert r.status_code == 201


# --- start, ready, serve, recall ---------------------------------------------------


async def _cooked(
    client: httpx.AsyncClient, seed: Seed, env: Menu, clock: FakeClock, engine: AsyncEngine
) -> tuple[Guest, dict[str, Any], dict[str, Any]]:
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item, 1)])).json()
    clock.advance(61)
    ticket = (await queue(client, seed))["queue"][0]
    await act(client, seed, ticket["id"], "start")
    ready = await act(client, seed, ticket["id"], "ready")
    assert ready.status_code == 200 and ready.json()["status"] == "ready"
    return g, placed, ticket


async def test_the_life_of_a_ticket_from_start_to_served(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    await assign(owner_engine, seed, "T1")
    g, placed, ticket = await _cooked(client, seed, env, fake_clock, owner_engine)
    assert await order_status(owner_engine, placed["id"]) == "ready"
    q = await queue(client, seed)
    assert q["queue"] == [] and [t["id"] for t in q["recent"]] == [ticket["id"]]
    assert (await card(client, seed, "T1"))["ready_rounds"] == 1

    served = await serve(client, seed, g, placed["id"])
    assert served.status_code == 200, served.text
    assert (served.json()["status"], served.json()["lines"][0]["status"]) == ("served", "served")
    assert await order_status(owner_engine, placed["id"]) == "served"
    async with owner_engine.connect() as conn:
        ticket_status = await conn.scalar(
            text("SELECT status FROM ticket WHERE id = :t"), {"t": uuid.UUID(ticket["id"])}
        )
    assert ticket_status == "bumped"
    assert (await queue(client, seed))["recent"] == []
    assert (await card(client, seed, "T1"))["state"] == "seated"

    log = [e for e, _ in await events(owner_engine, g.tab_id)]
    assert log == [
        "opened",
        "line_added",
        "order_placed",
        "order_accepted",
        "ticket_started",
        "order_preparing",
        "ticket_ready",
        "order_ready",
        "line_served",
        "order_served",
    ]
    guest_view = (await g.tab())["rounds"][0]
    assert (guest_view["status"], guest_view["lines"][0]["status"]) == ("served", "served")


async def card(client: httpx.AsyncClient, seed: Seed, label: str) -> dict[str, Any]:
    rows = (await client.get(f"{floor(seed)}/table-map", headers=manager(seed))).json()["tables"]
    return dict(next(t for t in rows if t["label"] == label))


async def test_only_ready_lines_can_be_served(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    await assign(owner_engine, seed, "T1")
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item)])).json()
    early = await serve(client, seed, g, placed["id"])
    assert (early.status_code, early.json()["code"]) == (409, "not_ready")
    fake_clock.advance(61)
    ticket = (await queue(client, seed))["queue"][0]
    await act(client, seed, ticket["id"], "start")
    assert (await serve(client, seed, g, placed["id"])).status_code == 409
    line_id = placed["lines"][0]["id"]
    assert (await serve(client, seed, g, placed["id"], {"line_ids": [line_id]})).status_code == 409
    assert (
        await serve(client, seed, g, placed["id"], {"line_ids": [str(uuid.uuid4())]})
    ).status_code == 404
    assert (await serve(client, seed, g, str(uuid.uuid4()))).status_code == 404


async def test_serving_is_role_and_table_checked(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    g, placed, _ = await _cooked(client, seed, env, fake_clock, owner_engine)
    assert (await serve(client, seed, g, placed["id"], who=kitchen(seed))).status_code == 403
    assert (
        await serve(client, seed, g, placed["id"])
    ).status_code == 404  # waiter isn't assigned to T1
    other = hdr(seed.token(seed.manager_b, Role.MANAGER, tenant="b"))
    assert (await serve(client, seed, g, placed["id"], who=other)).status_code == 403
    assert (await serve(client, seed, g, placed["id"], who=manager(seed))).status_code == 200


async def test_a_round_is_served_line_by_line(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    await assign(owner_engine, seed, "T1")
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item, 1), one(env.item, 2)])).json()
    fake_clock.advance(61)
    ticket = (await queue(client, seed))["queue"][0]
    await act(client, seed, ticket["id"], "start")
    await act(client, seed, ticket["id"], "ready")
    first, second = (line["id"] for line in placed["lines"])

    part = await serve(client, seed, g, placed["id"], {"line_ids": [first]})
    assert [line["id"] for line in part.json()["lines"]] == [first, second]  # entered order
    assert [line["status"] for line in part.json()["lines"]] == ["served", "ready"]
    assert part.json()["status"] == "ready"  # not served until every line is
    async with owner_engine.connect() as conn:
        assert (
            await conn.scalar(
                text("SELECT status FROM ticket WHERE id = :t"), {"t": uuid.UUID(ticket["id"])}
            )
            == "ready"
        )
    rest = await serve(client, seed, g, placed["id"])
    assert (rest.json()["status"], [line["status"] for line in rest.json()["lines"]]) == (
        "served",
        ["served", "served"],
    )
    again = await serve(client, seed, g, placed["id"], {"line_ids": [first]})
    assert again.status_code == 200  # serving what's already served is a no-op


async def test_a_bumped_ticket_can_be_recalled_until_something_is_served(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    await assign(owner_engine, seed, "T1")
    g, placed, ticket = await _cooked(client, seed, env, fake_clock, owner_engine)
    back = await act(client, seed, ticket["id"], "recall")
    assert back.status_code == 200 and back.json()["status"] == "preparing"
    assert await order_lines(owner_engine, placed["id"]) == ["preparing"]
    assert (await queue(client, seed))["recent"] == []
    await act(client, seed, ticket["id"], "ready")
    await serve(client, seed, g, placed["id"])
    late = await act(client, seed, ticket["id"], "recall")
    assert (late.status_code, late.json()["code"]) == (409, "illegal_transition")
    log = [e for e, _ in await events(owner_engine, g.tab_id)]
    assert "ticket_recalled" in log


async def test_recall_after_a_partial_serve_is_refused(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    await assign(owner_engine, seed, "T1")
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item, 1), one(env.item, 2)])).json()
    fake_clock.advance(61)
    ticket = (await queue(client, seed))["queue"][0]
    await act(client, seed, ticket["id"], "start")
    await act(client, seed, ticket["id"], "ready")
    await serve(client, seed, g, placed["id"], {"line_ids": [placed["lines"][0]["id"]]})
    refused = await act(client, seed, ticket["id"], "recall")
    assert (refused.status_code, refused.json()["code"]) == (409, "already_served")


async def test_illegal_ticket_moves_are_409_with_the_state(
    client: httpx.AsyncClient, seed: Seed, env: Menu, fake_clock: FakeClock
) -> None:
    g = await new_guest(client, seed)
    await g.order([one(env.item)])
    fake_clock.advance(61)
    ticket = (await queue(client, seed))["queue"][0]
    not_started = await act(client, seed, ticket["id"], "ready")
    assert (not_started.status_code, not_started.json()["code"]) == (409, "illegal_transition")
    assert not_started.json()["details"]["current"] == "queued"
    await act(client, seed, ticket["id"], "start")
    twice = await act(client, seed, ticket["id"], "start")
    assert twice.status_code == 409
    assert (await act(client, seed, str(uuid.uuid4()), "start")).status_code == 404


async def test_ticket_actions_are_idempotent_with_a_key(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    g = await new_guest(client, seed)
    await g.order([one(env.item)])
    fake_clock.advance(61)
    ticket = (await queue(client, seed))["queue"][0]
    headers = {**kitchen(seed), "Idempotency-Key": str(uuid.uuid4())}
    first = await client.post(f"{base(seed)}/tickets/{ticket['id']}/start", headers=headers)
    replay = await client.post(f"{base(seed)}/tickets/{ticket['id']}/start", headers=headers)
    assert first.status_code == replay.status_code == 200 and first.json() == replay.json()
    log = [e for e, _ in await events(owner_engine, g.tab_id)]
    assert log.count("ticket_started") == 1


# --- roles and tenants ---------------------------------------------------------------


async def test_the_queue_is_for_kitchen_bar_and_managers_only(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    g = await new_guest(client, seed)
    await g.order([one(env.item)])
    ticket = (await queue(client, seed))["queue"][0]
    assert (await client.get(f"{base(seed)}/tickets", headers=waiter(seed))).status_code == 403
    assert (await client.get(f"{base(seed)}/tickets")).status_code == 401
    assert (await client.get(f"{base(seed)}/tickets", headers=hdr(g.token))).status_code == 401
    outsider = hdr(seed.token(seed.manager_b, Role.MANAGER, tenant="b"))
    assert (await client.get(f"{base(seed)}/tickets", headers=outsider)).status_code == 403
    for verb in ("start", "ready", "recall"):
        assert (await act(client, seed, ticket["id"], verb, waiter(seed))).status_code == 403
        assert (await act(client, seed, ticket["id"], verb, outsider)).status_code == 403
    assert len((await queue(client, seed, manager(seed)))["queue"]) == 1


# --- stations ---------------------------------------------------------------------


async def test_items_on_different_stations_get_their_own_tickets(
    client: httpx.AsyncClient,
    seed: Seed,
    env: Menu,
    fake_clock: FakeClock,
    owner_engine: AsyncEngine,
) -> None:
    owner = staff(seed, seed.owner_a, Role.OWNER)
    bar = (await client.post(f"{env.base}/stations", json={"name": "G Bar"}, headers=owner)).json()
    hot = (
        await client.post(f"{env.base}/stations", json={"name": "G Kitchen"}, headers=owner)
    ).json()
    drink = (
        await client.post(
            f"{env.base}/items",
            json={
                "category_id": env.category["id"],
                "name": "G Lime Soda",
                "base_price_paise": 9000,
                "tax_class_id": env.tax_food["id"],
                "station_id": bar["id"],
            },
            headers=owner,
        )
    ).json()
    await client.put(
        f"{env.base}/items/{env.item['id']}",
        json={
            "category_id": env.category["id"],
            "name": env.item["name"],
            "base_price_paise": 32000,
            "tax_class_id": env.tax_food["id"],
            "station_id": hot["id"],
        },
        headers=owner,
    )
    await assign(owner_engine, seed, "T1")
    g = await new_guest(client, seed)
    placed = (await g.order([one(env.item), {"menu_item_id": drink["id"], "qty": 1}])).json()

    tickets = (await queue(client, seed))["queue"]
    assert sorted(t["station_name"] for t in tickets) == ["G Bar", "G Kitchen"]
    assert [
        t["station_name"] for t in (await queue(client, seed, station_id=bar["id"]))["queue"]
    ] == ["G Bar"]
    assert (await queue(client, seed, station_id=str(uuid.uuid4())))["queue"] == []

    fake_clock.advance(61)
    kitchen_ticket = next(t for t in tickets if t["station_name"] == "G Kitchen")
    bar_ticket = next(t for t in tickets if t["station_name"] == "G Bar")
    await act(client, seed, bar_ticket["id"], "start")
    assert await order_status(owner_engine, placed["id"]) == "preparing"
    await act(client, seed, bar_ticket["id"], "ready")
    assert await order_status(owner_engine, placed["id"]) == "preparing"  # the kitchen isn't done
    served = await serve(client, seed, g, placed["id"])
    assert [line["status"] for line in served.json()["lines"]].count("served") == 1
    await act(client, seed, kitchen_ticket["id"], "start")
    await act(client, seed, kitchen_ticket["id"], "ready")
    assert await order_status(owner_engine, placed["id"]) == "ready"
    await serve(client, seed, g, placed["id"])
    assert await order_status(owner_engine, placed["id"]) == "served"


async def test_unrouted_items_show_on_every_stations_screen(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    owner = staff(seed, seed.owner_a, Role.OWNER)
    bar = (await client.post(f"{env.base}/stations", json={"name": "G Bar2"}, headers=owner)).json()
    g = await new_guest(client, seed)
    await g.order([one(env.item)])  # the seed item has no station
    only_bar = (await queue(client, seed, station_id=bar["id"]))["queue"]
    assert len(only_bar) == 1 and only_bar[0]["station_name"] is None


# --- sold out ----------------------------------------------------------------------


async def test_kitchen_marks_an_item_sold_out_and_back(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    url = f"{base(seed)}/items/{env.item['id']}/sold-out"
    g = await new_guest(client, seed)
    off = await client.put(url, json={"sold_out": True}, headers=kitchen(seed))
    assert off.status_code == 200 and off.json()["available"] is False
    menu_item = next(
        i for c in (await g.menu())["categories"] for i in c["items"] if i["id"] == env.item["id"]
    )
    assert menu_item["available"] is False
    refused = await g.order([one(env.item)])
    assert (refused.status_code, refused.json()["code"]) == (409, "item_unavailable")
    on = await client.put(url, json={"sold_out": False}, headers=kitchen(seed))
    assert on.json()["available"] is True
    assert (await g.order([one(env.item)])).status_code == 201


async def test_sold_out_is_role_and_tenant_checked(
    client: httpx.AsyncClient, seed: Seed, env: Menu
) -> None:
    url = f"{base(seed)}/items/{env.item['id']}/sold-out"
    assert (await client.put(url, json={"sold_out": True}, headers=waiter(seed))).status_code == 403
    assert (await client.put(url, json={"sold_out": True})).status_code == 401
    outsider = hdr(seed.token(seed.manager_b, Role.MANAGER, tenant="b"))
    assert (await client.put(url, json={"sold_out": True}, headers=outsider)).status_code == 403
    missing = await client.put(
        f"{base(seed)}/items/{uuid.uuid4()}/sold-out",
        json={"sold_out": True},
        headers=kitchen(seed),
    )
    assert missing.status_code == 404
    assert (
        await client.put(url, json={"sold_out": True}, headers=manager(seed))
    ).status_code == 200
