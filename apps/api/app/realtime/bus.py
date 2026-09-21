"""Redis pub/sub fan-out: one channel per outlet, so every API replica delivers
an event to the sockets it holds (CLAUDE.md §2). The database, not Redis, is the
source of truth: a client that missed messages resumes from `tab_event`."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import redis.asyncio as redis

from app.config import settings


def outlet_channel(outlet_id: UUID) -> str:
    return f"outlet:{outlet_id}"


class EventBus:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client: redis.Redis | None = None

    def _redis(self) -> redis.Redis:
        if self._client is None:
            # redis 6.4 (the newest Celery's transport supports) leaves `from_url` untyped.
            self._client = redis.from_url(self._url, decode_responses=True)  # type: ignore[no-untyped-call]
        return self._client

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        await self._redis().publish(channel, json.dumps(message))

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        """Subscribed by the time the context is entered, so nothing published
        afterwards is missed while the caller replays history."""
        pubsub = self._redis().pubsub()
        await pubsub.subscribe(channel)

        async def messages() -> AsyncIterator[dict[str, Any]]:
            async for raw in pubsub.listen():
                if raw["type"] == "message":
                    yield json.loads(raw["data"])

        try:
            yield messages()
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()  # type: ignore[no-untyped-call]

    async def schedule(self, key: str, member: str, due_ts: float) -> None:
        """Remember `member` to be handled at `due_ts` (a sorted set scored by time)."""
        await self._redis().zadd(key, {member: due_ts})

    async def claim_due(self, key: str, now_ts: float, limit: int = 50) -> list[str]:
        """Members due by `now_ts`. Each is claimed with ZREM, so when several API
        replicas sweep at once exactly one of them gets a given member."""
        claimed: list[str] = []
        for member in await self._redis().zrangebyscore(key, "-inf", now_ts, start=0, num=limit):
            name = str(member)
            if await self._redis().zrem(key, name):
                claimed.append(name)
        return claimed

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


bus = EventBus(settings.redis_url)
