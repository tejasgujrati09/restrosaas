from __future__ import annotations

import uuid

import httpx
import pytest

from app.core.permissions import Role
from tests.api.helpers import Menu, build_menu, cleanup_menu
from tests.conftest import Seed, hdr

CSV_HEADER = "category,item,description,price,tax_class,veg,is_liquor,station,available,sku,modifier_groups\n"


@pytest.fixture
async def menu(client: httpx.AsyncClient, seed: Seed):  # type: ignore[no-untyped-def]
    built = await build_menu(client, seed, "I")
    yield built
    await cleanup_menu(client, built)


def csv(*rows: str) -> str:
    return CSV_HEADER + "\n".join(rows) + "\n"


async def preview(client: httpx.AsyncClient, menu: Menu, body: str | bytes) -> httpx.Response:
    return await client.post(
        f"{menu.base}/menu/import/preview",
        content=body,
        headers={**menu.owner, "content-type": "text/csv"},
    )


async def apply(
    client: httpx.AsyncClient, menu: Menu, body: str, diff_hash: str, key: uuid.UUID | None = None
) -> httpx.Response:
    headers = {**menu.owner, "content-type": "text/csv"}
    if key:
        headers["Idempotency-Key"] = str(key)
    return await client.post(
        f"{menu.base}/menu/import/apply?diff_hash={diff_hash}", content=body, headers=headers
    )


async def test_preview_shows_diff_without_writing(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    body = csv(
        "I Starters,I Paneer Tikka,,320,I Food 5%,yes,no,,yes,,",
        "I Starters,I Spring Roll,,150.50,I Food 5%,yes,no,,yes,,",
        "I Desserts,I Kulfi,,90,I Food 5%,,,,,,",
    )
    r = await preview(client, menu, body)
    assert r.status_code == 200
    data = r.json()
    assert data["errors"] == [] and len(data["diff_hash"]) == 64
    assert data["new_categories"] == ["I Desserts"]
    assert {a["item"]: a["price_paise"] for a in data["added"]} == {
        "I Spring Roll": 15050,
        "I Kulfi": 9000,
    }
    assert data["unchanged"] == 1 and data["changed"] == []
    tree = (await client.get(f"{menu.base}/menu", headers=menu.owner)).json()
    assert [c["name"] for c in tree["categories"]] == ["I Starters"]  # nothing was written


async def test_preview_reports_row_errors_and_no_hash(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    r = await preview(client, menu, csv("I Starters,I Bad,,abc,No such class,,,,,,"))
    data = r.json()
    assert data["diff_hash"] is None
    assert {(e["row"], e["column"]) for e in data["errors"]} == {(2, "price"), (2, "tax_class")}


async def test_apply_adds_updates_and_leaves_missing_items_alone(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    group = (
        await client.post(
            f"{menu.base}/modifier-groups", json={"name": "I Spice"}, headers=menu.owner
        )
    ).json()
    station = (
        await client.post(f"{menu.base}/stations", json={"name": "I Kitchen"}, headers=menu.owner)
    ).json()
    body = csv(
        "I Starters,I Paneer Tikka,Now smoky,350,I Food 5%,no,no,I Kitchen,yes,SKU9,I Spice",
        "I Desserts,I Kulfi,,90,I Food 5%,,,,,,",
    )
    dry = (await preview(client, menu, body)).json()
    assert dry["changed"][0]["changes"]["price_paise"] == [32000, 35000]

    r = await apply(client, menu, body, dry["diff_hash"])
    assert r.status_code == 200
    assert r.json() == {"categories_added": 1, "items_added": 1, "items_updated": 1}

    tree = (await client.get(f"{menu.base}/menu", headers=menu.owner)).json()
    items = {i["name"]: i for c in tree["categories"] for i in c["items"]}
    tikka = items["I Paneer Tikka"]
    assert (
        tikka["base_price_paise"],
        tikka["veg_flag"],
        tikka["station_id"],
        tikka["modifier_group_ids"],
    ) == (
        35000,
        False,
        station["id"],
        [group["id"]],
    )
    assert items["I Kulfi"]["base_price_paise"] == 9000
    assert [c["name"] for c in tree["categories"]] == ["I Desserts", "I Starters"] or len(
        tree["categories"]
    ) == 2

    # An item that is absent from a later file is reported but never deleted.
    later = (await preview(client, menu, csv("I Desserts,I Kulfi,,90,I Food 5%,,,,,,"))).json()
    assert ["I Starters", "I Paneer Tikka"] in later["not_in_file"]


async def test_apply_refuses_when_the_file_has_errors_or_the_menu_changed(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    bad = csv("I Starters,I Bad,,abc,I Food 5%,,,,,,")
    r = await apply(client, menu, bad, "0" * 64)
    assert (r.status_code, r.json()["code"]) == (409, "import_has_errors")

    body = csv("I Starters,I New,,10,I Food 5%,,,,,,")
    diff_hash = (await preview(client, menu, body)).json()["diff_hash"]
    await client.post(f"{menu.base}/items", json={**menu.item, "name": "I New"}, headers=menu.owner)
    stale = await apply(client, menu, body, diff_hash)
    assert (stale.status_code, stale.json()["code"]) == (409, "menu_changed")


async def test_apply_is_idempotent(client: httpx.AsyncClient, seed: Seed, menu: Menu) -> None:
    body = csv("I Starters,I Once,,10,I Food 5%,,,,,,")
    diff_hash = (await preview(client, menu, body)).json()["diff_hash"]
    key = uuid.uuid4()
    first = await apply(client, menu, body, diff_hash, key)
    replay = await apply(client, menu, body, diff_hash, key)
    assert first.status_code == replay.status_code == 200
    assert (
        first.json()
        == replay.json()
        == {"categories_added": 0, "items_added": 1, "items_updated": 0}
    )


async def test_export_then_import_is_a_no_op(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    exported = await client.get(f"{menu.base}/menu/export.csv", headers=menu.owner)
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("text/csv")
    assert exported.text.splitlines()[0] == CSV_HEADER.strip()
    assert "I Paneer Tikka,,320.00,I Food 5%,yes,no" in exported.text
    data = (await preview(client, menu, exported.text)).json()
    assert (
        data["errors"] == []
        and data["added"] == []
        and data["changed"] == []
        and data["unchanged"] == 1
    )


async def test_excel_bom_is_accepted_and_non_utf8_is_rejected(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    ok = await preview(
        client, menu, ("﻿" + csv("I Starters,I Bom,,10,I Food 5%,,,,,,")).encode("utf-8")
    )
    assert ok.status_code == 200 and ok.json()["errors"] == []
    bad = await preview(client, menu, b"category,item\n\xff\xfe\x00")
    assert (bad.status_code, bad.json()["code"]) == (422, "not_utf8")


async def test_oversized_file_is_rejected(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    r = await preview(client, menu, "x" * 1_000_001)
    assert (r.status_code, r.json()["code"]) == (413, "file_too_large")


async def test_import_is_owner_only_and_tenant_scoped(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    body = csv("I Starters,I X,,10,I Food 5%,,,,,,")
    manager = {**hdr(seed.token(seed.manager_a, Role.MANAGER)), "content-type": "text/csv"}
    assert (
        await client.post(f"{menu.base}/menu/import/preview", content=body, headers=manager)
    ).status_code == 403
    other = {**hdr(seed.token(seed.owner_b, Role.OWNER, tenant="b")), "content-type": "text/csv"}
    assert (
        await client.post(f"{menu.base}/menu/import/preview", content=body, headers=other)
    ).status_code == 403
