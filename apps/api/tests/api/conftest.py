from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import clock
from app.api.v1.voice_agent import get_voice_platform
from app.config import settings
from app.domains.voice import jobs as jobs_module
from app.domains.voice import provisioning
from app.domains.voice.platform import PhoneNumber
from app.main import app
from app.realtime import scheduler
from tests.api.guest_helpers import FRIDAY_7PM_IST, FakeClock, wipe_tabs
from tests.api.helpers import Menu, build_menu, cleanup_menu
from tests.conftest import Seed
from tests.voice_fakes import FakeVoicePlatform

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


# ---- voice ordering ----------------------------------------------------------------------

FREE_NUMBER = (1001, "+910000000001")
BUSY_NUMBER = (1002, "+910000000002")


class VoiceJobs:
    """Stands in for the job queue: records what the API asked for and runs it on demand
    against the fake platform, so a test decides exactly when the worker gets to act."""

    def __init__(self, fake: FakeVoicePlatform) -> None:
        self.fake = fake
        self.queue: list[tuple[str, uuid.UUID, uuid.UUID]] = []

    def dispatch(
        self, kind: str, restaurant_id: uuid.UUID, outlet_id: uuid.UUID, delay: int
    ) -> None:
        self.queue.append((kind, restaurant_id, outlet_id))

    async def run_one(self, *, final: bool = False) -> provisioning.JobOutcome:
        job = self.queue.pop(0)
        kind, restaurant_id, outlet_id = job
        if kind == "enable":
            outcome = await provisioning.run_enable(
                self.fake,
                restaurant_id=restaurant_id,
                outlet_id=outlet_id,
                tools_base_url="https://tools.example.test",
                preferred_number=settings.voice_sr_number,
                final=final,
            )
        else:
            outcome = await provisioning.run_disable(
                self.fake, restaurant_id=restaurant_id, outlet_id=outlet_id, final=final
            )
        if outcome == provisioning.JobOutcome.RETRY:
            self.queue.append(job)  # what the worker's delayed retry does
        return outcome

    async def run_all(self, *, max_retries: int = 5) -> list[provisioning.JobOutcome]:
        """Runs everything queued, including retries; the last allowed attempt is final."""
        outcomes: list[provisioning.JobOutcome] = []
        retries = 0
        while self.queue:
            outcome = await self.run_one(final=retries >= max_retries)
            outcomes.append(outcome)
            retries += outcome == provisioning.JobOutcome.RETRY
        return outcomes


@pytest.fixture
def jobs(voice_platform: FakeVoicePlatform) -> VoiceJobs:
    runner = VoiceJobs(voice_platform)
    jobs_module.set_dispatcher(runner.dispatch)
    return runner


@pytest.fixture
async def voice_platform(
    seed: Seed, owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FakeVoicePlatform]:
    fake = FakeVoicePlatform(numbers=[FREE_NUMBER, BUSY_NUMBER])
    fake.numbers[BUSY_NUMBER[0]] = PhoneNumber(
        BUSY_NUMBER[0], BUSY_NUMBER[1], "someone-elses-agent"
    )
    app.dependency_overrides[get_voice_platform] = lambda: fake
    monkeypatch.setattr(settings, "voice_tools_base_url", "https://tools.example.test")
    monkeypatch.setattr(settings, "voice_sr_number", None)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE restaurant SET voice_orders_allowed = true WHERE id = :r"),
            {"r": seed.restaurant_a},
        )
    yield fake
    app.dependency_overrides.pop(get_voice_platform, None)
    jobs_module.set_dispatcher(None)
    await wipe_tabs(owner_engine, seed)
    async with owner_engine.begin() as conn:
        for table in (
            "voice_provisioning_attempt",
            "customer_address",
            "customer",
            "voice_agent",
            "idempotency_key",
        ):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE restaurant_id = :r"), {"r": seed.restaurant_a}
            )
        await conn.execute(
            text(
                "DELETE FROM audit_log WHERE restaurant_id = :r "
                "AND (action LIKE 'voice.%' OR action LIKE 'restaurant.voice_%')"
            ),
            {"r": seed.restaurant_a},
        )
        await conn.execute(
            text("UPDATE restaurant SET voice_orders_allowed = false WHERE id = :r"),
            {"r": seed.restaurant_a},
        )
