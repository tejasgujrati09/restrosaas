from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text

from app.core.permissions import Role
from app.db.session import tenant_session
from tests.api.helpers import Menu, build_menu, cleanup_menu
from tests.conftest import Seed, hdr


@pytest.fixture
async def menu(client: httpx.AsyncClient, seed: Seed):  # type: ignore[no-untyped-def]
    built = await build_menu(client, seed, "M")
    yield built
    await cleanup_menu(client, built)


async def test_menu_tree_lists_everything_for_any_staff_role(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    r = await client.get(f"{menu.base}/menu", headers=hdr(seed.token(seed.kitchen_a, Role.KITCHEN)))
    assert r.status_code == 200
    body = r.json()
    assert body["prices_include_tax"] is True
    assert [t["name"] for t in body["tax_classes"]] == ["M Food 5%", "M Liquor VAT"]
    (category,) = body["categories"]
    assert category["items"][0]["name"] == "M Paneer Tikka"
    assert category["items"][0]["base_price_paise"] == 32000


async def test_only_owner_can_edit_menu_but_manager_can_toggle_availability(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    manager = hdr(seed.token(seed.manager_a, Role.MANAGER))
    waiter = hdr(seed.token(seed.waiter_a, Role.WAITER))
    body = {"name": "X", "gst_rate_bp": 500}
    assert (
        await client.post(f"{menu.base}/tax-classes", json=body, headers=manager)
    ).status_code == 403
    assert (
        await client.post(f"{menu.base}/tax-classes", json=body, headers=waiter)
    ).status_code == 403

    item_id = menu.item["id"]
    off = await client.put(
        f"{menu.base}/items/{item_id}/availability", json={"available": False}, headers=manager
    )
    assert off.status_code == 200 and off.json()["available"] is False
    denied = await client.put(
        f"{menu.base}/items/{item_id}/availability", json={"available": True}, headers=waiter
    )
    assert denied.status_code == 403
    # Availability is all a manager may change; the price is untouched.
    assert off.json()["base_price_paise"] == 32000


async def test_item_update_and_price_is_stored_exactly_as_typed(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    body = {**menu.item, "base_price_paise": 33050, "description": "Smoky"}
    r = await client.put(f"{menu.base}/items/{menu.item['id']}", json=body, headers=menu.owner)
    assert r.status_code == 200
    assert r.json()["base_price_paise"] == 33050
    assert r.json()["description"] == "Smoky"


async def test_liquor_needs_liquor_tax_class_and_licensed_outlet(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    base_item = {
        "category_id": menu.category["id"],
        "name": "M Whisky",
        "base_price_paise": 45000,
        "is_liquor": True,
    }
    wrong_tax = await client.post(
        f"{menu.base}/items",
        json={**base_item, "tax_class_id": menu.tax_food["id"]},
        headers=menu.owner,
    )
    assert (wrong_tax.status_code, wrong_tax.json()["code"]) == (422, "liquor_tax_mismatch")

    unlicensed = await client.post(
        f"{menu.base}/items",
        json={**base_item, "tax_class_id": menu.tax_liquor["id"]},
        headers=menu.owner,
    )
    assert unlicensed.status_code == 422
    assert unlicensed.json()["details"]["field"] == "is_liquor"

    await client.patch(f"{menu.base}/settings", json={"liquor_licensed": True}, headers=menu.owner)
    ok = await client.post(
        f"{menu.base}/items",
        json={**base_item, "tax_class_id": menu.tax_liquor["id"]},
        headers=menu.owner,
    )
    assert ok.status_code == 201
    await client.delete(f"{menu.base}/items/{ok.json()['id']}", headers=menu.owner)
    await client.patch(f"{menu.base}/settings", json={"liquor_licensed": False}, headers=menu.owner)


async def test_food_item_with_liquor_tax_class_is_rejected(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    r = await client.post(
        f"{menu.base}/items",
        json={
            "category_id": menu.category["id"],
            "name": "M Soda",
            "base_price_paise": 5000,
            "tax_class_id": menu.tax_liquor["id"],
        },
        headers=menu.owner,
    )
    assert r.json()["code"] == "liquor_tax_mismatch"


async def test_liquor_tax_class_cannot_carry_gst(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    r = await client.post(
        f"{menu.base}/tax-classes",
        json={"name": "M Bad", "gst_rate_bp": 500, "liquor_vat": True},
        headers=menu.owner,
    )
    assert r.status_code == 422


async def test_duplicate_names_conflict_case_insensitively(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    dup_item = {**menu.item, "name": "m paneer tikka"}
    r = await client.post(f"{menu.base}/items", json=dup_item, headers=menu.owner)
    assert (r.status_code, r.json()["code"]) == (409, "duplicate")
    dup_cat = await client.post(
        f"{menu.base}/categories", json={"name": "m STARTERS"}, headers=menu.owner
    )
    assert dup_cat.status_code == 409


async def test_in_use_records_cannot_be_deleted(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    for path in (f"categories/{menu.category['id']}", f"tax-classes/{menu.tax_food['id']}"):
        r = await client.delete(f"{menu.base}/{path}", headers=menu.owner)
        assert (r.status_code, r.json()["code"]) == (409, "in_use")


async def test_references_must_belong_to_the_same_outlet(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    other = hdr(seed.token(seed.owner_b, Role.OWNER, tenant="b"))
    other_base = f"/v1/outlets/{seed.outlet_b}"
    foreign_cat = (
        await client.post(f"{other_base}/categories", json={"name": "B cat"}, headers=other)
    ).json()
    r = await client.post(
        f"{menu.base}/items",
        json={**menu.item, "name": "M Foreign", "category_id": foreign_cat["id"]},
        headers=menu.owner,
    )
    assert (r.status_code, r.json()["code"]) == (404, "not_found")
    await client.delete(f"{other_base}/categories/{foreign_cat['id']}", headers=other)


async def test_modifier_groups_and_item_links(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    group = await client.post(
        f"{menu.base}/modifier-groups",
        json={
            "name": "M Spice",
            "min_select": 1,
            "max_select": 1,
            "modifiers": [{"name": "Mild"}, {"name": "Hot", "price_delta_paise": 1000}],
        },
        headers=menu.owner,
    )
    assert group.status_code == 201
    group_id = group.json()["id"]
    assert [m["name"] for m in group.json()["modifiers"]] == ["Hot", "Mild"]

    linked = await client.put(
        f"{menu.base}/items/{menu.item['id']}",
        json={**menu.item, "modifier_group_ids": [group_id]},
        headers=menu.owner,
    )
    assert linked.json()["modifier_group_ids"] == [group_id]

    extra = await client.post(
        f"{menu.base}/modifier-groups/{group_id}/modifiers",
        json={"name": "Extra hot", "price_delta_paise": 2000},
        headers=menu.owner,
    )
    assert extra.status_code == 201
    renamed = await client.put(
        f"{menu.base}/modifier-groups/{group_id}/modifiers/{extra.json()['id']}",
        json={"name": "Fiery", "price_delta_paise": 2500},
        headers=menu.owner,
    )
    assert renamed.json()["price_delta_paise"] == 2500
    updated = await client.put(
        f"{menu.base}/modifier-groups/{group_id}",
        json={"name": "M Spice level", "min_select": 0, "max_select": 2},
        headers=menu.owner,
    )
    assert updated.json()["max_select"] == 2
    assert (
        await client.delete(
            f"{menu.base}/modifier-groups/{group_id}/modifiers/{extra.json()['id']}",
            headers=menu.owner,
        )
    ).status_code == 204

    bad_range = await client.post(
        f"{menu.base}/modifier-groups",
        json={"name": "M Bad", "min_select": 3, "max_select": 1},
        headers=menu.owner,
    )
    assert bad_range.status_code == 422
    missing = await client.put(
        f"{menu.base}/modifier-groups/{group_id}/modifiers/{menu.item['id']}",
        json={"name": "x"},
        headers=menu.owner,
    )
    assert missing.status_code == 404

    # Deleting the group unlinks it from items first.
    await client.put(
        f"{menu.base}/items/{menu.item['id']}",
        json={**menu.item, "modifier_group_ids": []},
        headers=menu.owner,
    )
    assert (
        await client.delete(f"{menu.base}/modifier-groups/{group_id}", headers=menu.owner)
    ).status_code == 204


async def test_stations_crud_and_item_station(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    station = (
        await client.post(f"{menu.base}/stations", json={"name": "M Kitchen"}, headers=menu.owner)
    ).json()
    renamed = await client.put(
        f"{menu.base}/stations/{station['id']}", json={"name": "M Main kitchen"}, headers=menu.owner
    )
    assert renamed.json()["name"] == "M Main kitchen"
    routed = await client.put(
        f"{menu.base}/items/{menu.item['id']}",
        json={**menu.item, "station_id": station["id"]},
        headers=menu.owner,
    )
    assert routed.json()["station_id"] == station["id"]
    await client.put(
        f"{menu.base}/items/{menu.item['id']}",
        json={**menu.item, "station_id": None},
        headers=menu.owner,
    )
    assert (
        await client.delete(f"{menu.base}/stations/{station['id']}", headers=menu.owner)
    ).status_code == 204


async def test_category_and_tax_class_update_and_delete(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    cat = (
        await client.post(f"{menu.base}/categories", json={"name": "M Temp"}, headers=menu.owner)
    ).json()
    upd = await client.put(
        f"{menu.base}/categories/{cat['id']}",
        json={
            "name": "M Temp2",
            "visible": False,
            "available_from": "07:00:00",
            "available_to": "11:00:00",
        },
        headers=menu.owner,
    )
    assert upd.json()["available_from"] == "07:00:00" and upd.json()["visible"] is False
    assert (
        await client.delete(f"{menu.base}/categories/{cat['id']}", headers=menu.owner)
    ).status_code == 204
    tax = (
        await client.post(
            f"{menu.base}/tax-classes",
            json={"name": "M Temp 18%", "gst_rate_bp": 1800},
            headers=menu.owner,
        )
    ).json()
    upd_tax = await client.put(
        f"{menu.base}/tax-classes/{tax['id']}",
        json={"name": "M Temp 12%", "gst_rate_bp": 1200},
        headers=menu.owner,
    )
    assert upd_tax.json()["gst_rate_bp"] == 1200
    assert (
        await client.delete(f"{menu.base}/tax-classes/{tax['id']}", headers=menu.owner)
    ).status_code == 204
    assert (
        await client.delete(f"{menu.base}/tax-classes/{tax['id']}", headers=menu.owner)
    ).status_code == 404


async def test_tenant_b_cannot_see_or_reach_tenant_a_menu(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    other = hdr(seed.token(seed.owner_b, Role.OWNER, tenant="b"))
    assert (await client.get(f"{menu.base}/menu", headers=other)).status_code == 403
    assert (
        await client.put(f"{menu.base}/items/{menu.item['id']}", json=menu.item, headers=other)
    ).status_code == 403
    # Same id through B's own outlet: the row exists in A's tenant only, so B gets 404.
    via_b = await client.put(
        f"/v1/outlets/{seed.outlet_b}/items/{menu.item['id']}", json=menu.item, headers=other
    )
    assert via_b.status_code == 404
    async with tenant_session(seed.restaurant_b) as session:
        assert await session.scalar(text("SELECT count(*) FROM menu_item")) == 0
        assert await session.scalar(text("SELECT count(*) FROM tax_class")) == 0


async def test_price_lock_precondition_editing_an_item_does_not_touch_other_rows(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    second = (
        await client.post(
            f"{menu.base}/items",
            json={**menu.item, "name": "M Other", "base_price_paise": 10000},
            headers=menu.owner,
        )
    ).json()
    await client.put(
        f"{menu.base}/items/{menu.item['id']}",
        json={**menu.item, "base_price_paise": 99900},
        headers=menu.owner,
    )
    tree = (await client.get(f"{menu.base}/menu", headers=menu.owner)).json()
    prices = {i["name"]: i["base_price_paise"] for c in tree["categories"] for i in c["items"]}
    assert prices == {"M Paneer Tikka": 99900, "M Other": 10000}
    assert second["base_price_paise"] == 10000


async def test_delete_replay_with_same_key_returns_204_again(
    client: httpx.AsyncClient, seed: Seed, menu: Menu
) -> None:
    import uuid

    key = uuid.uuid4()
    cat = (
        await client.post(f"{menu.base}/categories", json={"name": "M Once"}, headers=menu.owner)
    ).json()
    first = await client.delete(
        f"{menu.base}/categories/{cat['id']}",
        headers=hdr(seed.token(seed.owner_a, Role.OWNER), key),
    )
    replay = await client.delete(
        f"{menu.base}/categories/{cat['id']}",
        headers=hdr(seed.token(seed.owner_a, Role.OWNER), key),
    )
    assert (first.status_code, replay.status_code) == (204, 204)
    no_key = await client.delete(f"{menu.base}/categories/{cat['id']}", headers=menu.owner)
    assert no_key.status_code == 404  # without the key a second delete is a real 404
