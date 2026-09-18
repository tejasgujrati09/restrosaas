"""Shared by the guest ordering and realtime tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.permissions import Role
from tests.conftest import Seed, hdr

# Friday 19:00 in Asia/Kolkata (13:30 UTC).
FRIDAY_7PM_IST = datetime(2026, 9, 18, 13, 30, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


async def wipe_tabs(owner_engine: AsyncEngine, seed: Seed) -> None:
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
