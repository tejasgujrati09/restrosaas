from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app import clock
from app.realtime import scheduler
from tests.api.guest_helpers import FRIDAY_7PM_IST, FakeClock, wipe_tabs
from tests.api.helpers import Menu, build_menu, cleanup_menu
from tests.conftest import Seed


@pytest.fixture(autouse=True)
def no_auto_accept_timers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timers are best effort and process-local; tests that want one turn it on themselves."""
    monkeypatch.setattr(scheduler, "ENABLED", False)


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
