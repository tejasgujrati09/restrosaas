from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app import clock
from app.config import settings
from app.realtime import scheduler
from tests.api.guest_helpers import FRIDAY_7PM_IST, FakeClock, wipe_tabs
from tests.api.helpers import Menu, build_menu, cleanup_menu
from tests.conftest import Seed

RUN_ID = uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def isolated_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scheduling is off unless a test is about it, and its Redis keys are private to
    this run so it can never drain (or be drained by) a dev stack sharing the Redis."""
    monkeypatch.setattr(scheduler, "ENABLED", False)
    monkeypatch.setattr(settings, "redis_key_prefix", f"test-{RUN_ID}")


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock(FRIDAY_7PM_IST)
    monkeypatch.setattr(clock, "utcnow", lambda: fake.now)
    return fake


@pytest.fixture
async def env(
    client: httpx.AsyncClient, seed: Seed, owner_engine: AsyncEngine
) -> AsyncIterator[Menu]:
    await wipe_tabs(owner_engine, seed)
    menu = await build_menu(client, seed, "G")
    yield menu
    await wipe_tabs(owner_engine, seed)
    await cleanup_menu(client, menu)
