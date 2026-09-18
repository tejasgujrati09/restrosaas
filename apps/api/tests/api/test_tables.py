from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.permissions import Role
from tests.api.helpers import build_menu, cleanup_menu
from tests.conftest import Seed, hdr


@pytest.fixture
async def base(seed: Seed) -> str:
    return f"/v1/outlets/{seed.outlet_a}"


async def _cleanup(client: httpx.AsyncClient, seed: Seed, base: str, prefix: str) -> None:
    owner = hdr(seed.token(seed.owner_a, Role.OWNER))
    for t in (await client.get(f"{base}/tables", headers=owner)).json():
        if t["label"].startswith(prefix):
            await client.delete(f"{base}/tables/{t['id']}", headers=owner)


async def test_table_crud_and_qr_visibility_by_role(
    client: httpx.AsyncClient, seed: Seed, base: str
) -> None:
    manager = hdr(seed.token(seed.manager_a, Role.MANAGER))
    created = await client.post(
        f"{base}/tables", json={"label": "Z1", "zone": "terrace", "seats": 4}, headers=manager
    )
    assert created.status_code == 201
    table = created.json()
    assert (
        table["qr_url"].startswith("http://localhost:3000/t/")
        and len(table["qr_url"].rsplit("/", 1)[1]) == 12
    )

    waiter_view = await client.get(
        f"{base}/tables", headers=hdr(seed.token(seed.waiter_a, Role.WAITER))
    )
    z1 = next(t for t in waiter_view.json() if t["label"] == "Z1")
    assert z1["qr_url"] is None  # waiters see tables, not QR links

    updated = await client.put(
        f"{base}/tables/{table['id']}",
        json={"label": "Z1", "zone": "terrace", "seats": 6, "active": False},
        headers=manager,
    )
    assert (updated.json()["seats"], updated.json()["active"]) == (6, False)
    assert updated.json()["qr_url"] == table["qr_url"]  # editing never rotates the QR
    dup = await client.post(f"{base}/tables", json={"label": "Z1"}, headers=manager)
    assert dup.status_code == 409
    assert (await client.delete(f"{base}/tables/{table['id']}", headers=manager)).status_code == 204
    assert (await client.delete(f"{base}/tables/{table['id']}", headers=manager)).status_code == 404


async def test_waiter_cannot_create_tables_and_tenant_b_cannot_reach_them(
    client: httpx.AsyncClient, seed: Seed, base: str
) -> None:
    waiter = hdr(seed.token(seed.waiter_a, Role.WAITER))
    assert (
        await client.post(f"{base}/tables", json={"label": "Z9"}, headers=waiter)
    ).status_code == 403
    other = hdr(seed.token(seed.owner_b, Role.OWNER, tenant="b"))
    assert (await client.get(f"{base}/tables", headers=other)).status_code == 403
    assert (await client.get(f"{base}/tables/qr-sheet.pdf", headers=other)).status_code == 403


async def test_bulk_create_gives_each_table_a_distinct_token(
    client: httpx.AsyncClient, seed: Seed, base: str
) -> None:
    owner = hdr(seed.token(seed.owner_a, Role.OWNER))
    r = await client.post(
        f"{base}/tables/bulk", json={"zone": "bar", "labels": ["BB1", "BB2", "BB3"]}, headers=owner
    )
    assert r.status_code == 201
    urls = [t["qr_url"] for t in r.json()]
    assert len(set(urls)) == 3
    assert {t["zone"] for t in r.json()} == {"bar"}
    dup = await client.post(f"{base}/tables/bulk", json={"labels": ["BB1"]}, headers=owner)
    assert dup.status_code == 409
    await _cleanup(client, seed, base, "BB")


async def test_rotate_qr_changes_the_link_and_is_audited(
    client: httpx.AsyncClient, seed: Seed, base: str, owner_engine: AsyncEngine
) -> None:
    owner = hdr(seed.token(seed.owner_a, Role.OWNER))
    table = (await client.post(f"{base}/tables", json={"label": "RQ1"}, headers=owner)).json()
    rotated = await client.post(f"{base}/tables/{table['id']}/rotate-qr", headers=owner)
    assert rotated.status_code == 200
    assert rotated.json()["qr_url"] != table["qr_url"]
    async with owner_engine.connect() as conn:
        count = await conn.scalar(
            text(
                "SELECT count(*) FROM audit_log WHERE restaurant_id = :r AND action = 'table.qr_rotated' AND target_id = :t"
            ),
            {"r": seed.restaurant_a, "t": table["id"]},
        )
    assert count == 1
    waiter = hdr(seed.token(seed.waiter_a, Role.WAITER))
    assert (
        await client.post(f"{base}/tables/{table['id']}/rotate-qr", headers=waiter)
    ).status_code == 403
    await _cleanup(client, seed, base, "RQ")


async def test_qr_sheet_pdf_has_a_page_per_zone(
    client: httpx.AsyncClient, seed: Seed, base: str
) -> None:
    owner = hdr(seed.token(seed.owner_a, Role.OWNER))
    await client.post(
        f"{base}/tables/bulk", json={"zone": "floor", "labels": ["QS1", "QS2"]}, headers=owner
    )
    await client.post(
        f"{base}/tables/bulk", json={"zone": "terrace", "labels": ["QS3"]}, headers=owner
    )
    r = await client.get(f"{base}/tables/qr-sheet.pdf", headers=owner)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    only_terrace = await client.get(
        f"{base}/tables/qr-sheet.pdf", params={"zone": "terrace"}, headers=owner
    )
    assert only_terrace.status_code == 200 and len(only_terrace.content) < len(r.content)
    empty = await client.get(
        f"{base}/tables/qr-sheet.pdf", params={"zone": "nowhere"}, headers=owner
    )
    assert empty.status_code == 404
    await _cleanup(client, seed, base, "QS")


async def test_menu_pdf_renders_visible_categories(client: httpx.AsyncClient, seed: Seed) -> None:
    menu = await build_menu(client, seed, "PDF")
    try:
        await client.post(
            f"{menu.base}/categories",
            json={"name": "PDF Hidden", "visible": False},
            headers=menu.owner,
        )
        r = await client.get(
            f"{menu.base}/menu.pdf", headers=hdr(seed.token(seed.waiter_a, Role.WAITER))
        )
        assert r.status_code == 200 and r.content.startswith(b"%PDF")
    finally:
        await cleanup_menu(client, menu)


def test_pdf_html_escapes_owner_supplied_text() -> None:
    from app.pdf import menu_html, qr_sheet_html

    hostile = "<script>alert(1)</script>"
    assert "<script>" not in menu_html(hostile, True, [(hostile, [(hostile, hostile, 100, True)])])
    assert "<script>" not in qr_sheet_html(hostile, {hostile: [(hostile, "<svg/>")]})
    assert "Taxes extra" in menu_html("B", False, [])


def test_qr_svg_encodes_the_table_url() -> None:
    from app.qr import new_qr_token, qr_svg

    token = new_qr_token()
    assert qr_svg(token).startswith("<svg")
    assert new_qr_token() != token


def test_qr_sheet_has_exactly_one_page_per_zone() -> None:
    from weasyprint import HTML

    from app.pdf import qr_sheet_html

    zones = {
        "floor": [(f"T{i}", "<svg/>") for i in range(1, 7)],
        "terrace": [("T7", "<svg/>")],
        "bar": [("B1", "<svg/>")],
    }
    assert len(HTML(string=qr_sheet_html("Brand", zones)).render().pages) == 3
