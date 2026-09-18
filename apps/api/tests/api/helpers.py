from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.permissions import Role
from tests.conftest import Seed, hdr


@dataclass
class Menu:
    """A small menu built through the API, for tests that need one."""

    base: str
    owner: dict[str, str]
    tax_food: dict[str, Any]
    tax_liquor: dict[str, Any]
    category: dict[str, Any]
    item: dict[str, Any]


async def build_menu(client: httpx.AsyncClient, seed: Seed, tag: str) -> Menu:
    owner = hdr(seed.token(seed.owner_a, Role.OWNER))
    base = f"/v1/outlets/{seed.outlet_a}"
    tax_food = (
        await client.post(
            f"{base}/tax-classes",
            json={"name": f"{tag} Food 5%", "gst_rate_bp": 500},
            headers=owner,
        )
    ).json()
    tax_liquor = (
        await client.post(
            f"{base}/tax-classes",
            json={"name": f"{tag} Liquor VAT", "gst_rate_bp": 0, "liquor_vat": True},
            headers=owner,
        )
    ).json()
    category = (
        await client.post(f"{base}/categories", json={"name": f"{tag} Starters"}, headers=owner)
    ).json()
    item = (
        await client.post(
            f"{base}/items",
            json={
                "category_id": category["id"],
                "name": f"{tag} Paneer Tikka",
                "base_price_paise": 32000,
                "tax_class_id": tax_food["id"],
            },
            headers=owner,
        )
    ).json()
    return Menu(base, owner, tax_food, tax_liquor, category, item)


async def cleanup_menu(client: httpx.AsyncClient, menu: Menu) -> None:
    """Delete in FK order so the shared seeded outlet stays clean between tests."""
    menu_state = (await client.get(f"{menu.base}/menu", headers=menu.owner)).json()
    for c in menu_state["categories"]:
        for i in c["items"]:
            await client.delete(f"{menu.base}/items/{i['id']}", headers=menu.owner)
        await client.delete(f"{menu.base}/categories/{c['id']}", headers=menu.owner)
    for g in menu_state["modifier_groups"]:
        await client.delete(f"{menu.base}/modifier-groups/{g['id']}", headers=menu.owner)
    for s in menu_state["stations"]:
        await client.delete(f"{menu.base}/stations/{s['id']}", headers=menu.owner)
    for t in menu_state["tax_classes"]:
        await client.delete(f"{menu.base}/tax-classes/{t['id']}", headers=menu.owner)


def new_key() -> uuid.UUID:
    return uuid.uuid4()
