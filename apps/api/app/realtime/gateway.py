"""WebSocket gateway: one channel per outlet, messages filtered by role, reconnect
with resume.

Protocol (JSON text frames)
  client -> server, first frame within 5 s:
      {"type": "auth", "token": "<staff JWT or TabSession token>", "last_event_id": 123 | null}
    The token travels in a frame, not the URL, so it never lands in access logs.
  server -> client:
      {"type": "ready"}                      subscribed; safe to fetch current state over REST
      {"type": "event", "id", "tab_id", "at", "event", "actor_type", "payload"}
      {"type": "resync"}                     too much was missed; refetch state
      {"type": "ping"}                       keep-alive every 25 s
  close codes: 4400 bad first frame, 4401 not authorised or session over, 4410 tab ended.

Delivery is "signal plus resume": the database is the source of truth. A client that
reconnects sends the last event id it saw and is replayed everything newer that its
role may see (up to 500 events, beyond which it is told to resync).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.auth import InvalidTokenError, decode_token
from app.core.permissions import PermissionDeniedError
from app.core.realtime import TAB_ENDING_EVENTS, Audience, may_receive, redact
from app.db.session import tenant_session
from app.deps import load_guest_session, load_staff_roles
from app.domains.tab.models import Tab, TabEvent
from app.errors import ApiError
from app.guest_auth import parse_session_token
from app.realtime.bus import bus, outlet_channel
from app.realtime.hooks import event_message

logger = structlog.get_logger()
router = APIRouter(tags=["realtime"])

AUTH_TIMEOUT_SECONDS = 5.0
HEARTBEAT_SECONDS = 25.0
REPLAY_LIMIT = 500

CLOSE_BAD_FRAME = 4400
CLOSE_UNAUTHORISED = 4401
CLOSE_TAB_ENDED = 4410


@dataclass(frozen=True)
class Connection:
    restaurant_id: UUID
    audience: Audience
    # Guests only: when their session lapses. Checked on every heartbeat.
    expires_at: datetime | None


async def _authenticate(token: str, outlet_id: UUID) -> Connection | None:
    """A staff JWT or a TabSession token. Roles and sessions are re-read from the
    database, exactly as for HTTP requests."""
    try:
        user_id, claims = decode_token(token)
    except InvalidTokenError:
        pass
    else:
        claim = next((c for c in claims if c.outlet_id == outlet_id), None)
        if claim is None:
            return None
        try:
            async with tenant_session(claim.restaurant_id) as session:
                roles = await load_staff_roles(session, user_id, outlet_id)
        except PermissionDeniedError:
            return None
        return Connection(claim.restaurant_id, Audience(tab_id=None, roles=roles), None)

    try:
        restaurant_id, token_hash = parse_session_token(token)
        async with tenant_session(restaurant_id) as session:
            tab_session, tab = await load_guest_session(session, token_hash, outlet_id)
    except (InvalidTokenError, ApiError, PermissionDeniedError):
        return None
    return Connection(
        restaurant_id, Audience(tab_id=tab.id, roles=frozenset()), tab_session.expires_at
    )


async def _replay(
    session: AsyncSession, conn: Connection, outlet_id: UUID, after: int
) -> list[TabEvent] | None:
    """Events newer than `after` this audience may see; None when there are too many."""
    query = (
        select(TabEvent).where(TabEvent.id > after).order_by(TabEvent.id).limit(REPLAY_LIMIT + 1)
    )
    if conn.audience.tab_id is not None:
        query = query.where(TabEvent.tab_id == conn.audience.tab_id)
    else:
        query = query.join(Tab, Tab.id == TabEvent.tab_id).where(Tab.outlet_id == outlet_id)
    rows = list((await session.scalars(query)).all())
    return None if len(rows) > REPLAY_LIMIT else rows


def _deliverable(audience: Audience, message: dict[str, Any]) -> dict[str, Any] | None:
    if not may_receive(audience, message["event"], UUID(message["tab_id"])):
        return None
    return {
        "type": "event",
        **{k: message[k] for k in ("id", "tab_id", "at", "event", "actor_type")},
        "payload": redact(audience, message["payload"]),
    }


@router.websocket("/v1/outlets/{outlet_id}/ws")
async def outlet_socket(ws: WebSocket, outlet_id: UUID) -> None:
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_json(), AUTH_TIMEOUT_SECONDS)
        token = first["token"]
        last_id = first.get("last_event_id")
        if first.get("type") != "auth" or not isinstance(token, str):
            raise ValueError
        if last_id is not None and not isinstance(last_id, int):
            raise ValueError
    except (TimeoutError, WebSocketDisconnect, KeyError, ValueError, TypeError):
        with contextlib.suppress(RuntimeError):
            await ws.close(CLOSE_BAD_FRAME)
        return

    conn = await _authenticate(token, outlet_id)
    if conn is None:
        await ws.close(CLOSE_UNAUTHORISED)
        return
    structlog.contextvars.bind_contextvars(
        restaurant_id=str(conn.restaurant_id), outlet_id=str(outlet_id)
    )

    try:
        async with bus.subscribe(outlet_channel(outlet_id)) as messages:
            # Subscribed before replaying, so nothing falls between the two.
            highest = last_id or 0
            if last_id is not None:
                async with tenant_session(conn.restaurant_id) as session:
                    missed = await _replay(session, conn, outlet_id, last_id)
                if missed is None:
                    await ws.send_json({"type": "resync"})
                else:
                    for row in missed:
                        out = _deliverable(conn.audience, event_message(row))
                        highest = max(highest, row.id)
                        if out:
                            await ws.send_json(out)
            await ws.send_json({"type": "ready"})

            async def pump() -> None:
                nonlocal highest
                async for message in messages:
                    if message["id"] <= highest:
                        continue
                    highest = message["id"]
                    out = _deliverable(conn.audience, message)
                    if out is None:
                        continue
                    await ws.send_json(out)
                    if conn.audience.is_guest and message["event"] in TAB_ENDING_EVENTS:
                        await ws.close(CLOSE_TAB_ENDED)
                        return

            async def listen() -> None:
                while True:  # clients send nothing after auth; this only notices a disconnect
                    await ws.receive_text()

            async def beat() -> None:
                while True:
                    await asyncio.sleep(HEARTBEAT_SECONDS)
                    if conn.expires_at is not None and conn.expires_at <= clock.utcnow():
                        await ws.close(CLOSE_UNAUTHORISED)
                        return
                    await ws.send_json({"type": "ping"})

            tasks = [asyncio.create_task(f()) for f in (pump, listen, beat)]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except (WebSocketDisconnect, RuntimeError):
        return
