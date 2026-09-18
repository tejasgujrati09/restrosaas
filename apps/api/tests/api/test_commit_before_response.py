"""A write must be committed before its response is sent. FastAPI runs a `yield`
dependency's exit code after the response unless told otherwise, which would let a
client's next request race the commit. These tests drive the ASGI app directly and
look at the database, from another connection, the instant the response completes."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.permissions import Role
from app.main import app
from tests.api.guest_helpers import Guest, new_guest, one, wipe_tabs
from tests.api.helpers import Menu, build_menu, cleanup_menu
from tests.conftest import Seed, hdr


async def call_and_inspect(
    method: str, path: str, headers: dict[str, str], body: Any, inspect: Any
) -> tuple[int, Any]:
    """Runs one request through the app; `inspect()` runs when the response is complete."""
    raw = json.dumps(body).encode() if body is not None else b""
    sent = {"done": False}
    status = 0
    seen: Any = None

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status, seen
        if message["type"] == "http.response.start":
            status = message["status"]
        if message["type"] == "http.response.body" and not message.get("more_body"):
            sent["done"] = True
            seen = await inspect()

    header_list = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    header_list.append((b"content-type", b"application/json"))
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": header_list,
        "http_version": "1.1",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1),
        "root_path": "",
    }
    await app(scope, receive, send)
    assert sent["done"]
    return status, seen


async def test_a_staff_write_is_visible_to_other_connections_when_the_response_completes(
    seed: Seed, owner_engine: AsyncEngine
) -> None:
    label = f"CB{uuid.uuid4().hex[:6]}"

    async def table_exists() -> bool:
        async with owner_engine.connect() as conn:
            found = await conn.scalar(
                text("SELECT count(*) FROM dining_table WHERE label = :l"), {"l": label}
            )
        return bool(found)

    status, visible = await call_and_inspect(
        "POST",
        f"/v1/outlets/{seed.outlet_a}/tables",
        hdr(seed.token(seed.owner_a, Role.OWNER)),
        {"label": label},
        table_exists,
    )
    assert status == 201
    assert visible is True, "the response was sent before the transaction committed"
    async with owner_engine.begin() as conn:
        await conn.execute(text("DELETE FROM dining_table WHERE label = :l"), {"l": label})


async def test_a_guest_order_is_committed_before_the_response_completes(
    client: Any, seed: Seed, owner_engine: AsyncEngine
) -> None:
    await wipe_tabs(owner_engine, seed)
    menu: Menu = await build_menu(client, seed, "CB")
    try:
        guest: Guest = await new_guest(client, seed)

        async def round_count() -> int:
            async with owner_engine.connect() as conn:
                return int(
                    await conn.scalar(
                        text("SELECT count(*) FROM tab_order WHERE tab_id = :t"),
                        {"t": uuid.UUID(guest.tab_id)},
                    )
                    or 0
                )

        status, count = await call_and_inspect(
            "POST",
            f"{guest.base}/orders",
            guest.headers(),
            {"lines": [one(menu.item)]},
            round_count,
        )
        assert status == 201
        assert count == 1, "the response was sent before the transaction committed"
    finally:
        await wipe_tabs(owner_engine, seed)
        await cleanup_menu(client, menu)
