"""The worker's plumbing without a broker: retry delays, and that the API's default dispatcher
sends the right task. The provisioning logic itself is tested in tests/api/test_voice_agent.py."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app import worker
from app.domains.voice import jobs


def test_backoff_grows_and_is_capped() -> None:
    assert [worker.backoff(n) for n in range(7)] == [5, 15, 45, 135, 300, 300, 300]


def test_the_default_dispatcher_sends_a_celery_task_with_the_ids_as_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        worker.celery_app, "send_task", lambda name, **kw: sent.append({"name": name, **kw})
    )
    jobs.set_dispatcher(None)
    restaurant, outlet = uuid.uuid4(), uuid.uuid4()
    jobs.enqueue("enable", restaurant, outlet)
    jobs.enqueue("disable", restaurant, outlet, delay=30)
    assert sent == [
        {"name": "voice.enable", "args": [str(restaurant), str(outlet)], "countdown": 0},
        {"name": "voice.disable", "args": [str(restaurant), str(outlet)], "countdown": 30},
    ]


def test_an_unreachable_queue_never_fails_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> None:
        raise ConnectionError("broker down")

    jobs.set_dispatcher(boom)
    try:
        jobs.enqueue("enable", uuid.uuid4(), uuid.uuid4())  # logged, not raised
    finally:
        jobs.set_dispatcher(None)


def test_tasks_are_registered_under_the_names_the_dispatcher_uses() -> None:
    assert {"voice.enable", "voice.disable"} <= set(worker.celery_app.tasks)
    assert worker.celery_app.conf.task_acks_late is True


def test_a_transient_outcome_becomes_a_delayed_celery_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from celery.exceptions import Retry

    from app.domains.voice.provisioning import JobOutcome

    monkeypatch.setattr(worker, "_run", lambda coro: (coro.close(), JobOutcome.RETRY)[1])
    monkeypatch.setattr(worker.factory, "tools_base_url", lambda: "https://tools.example.test")
    monkeypatch.setattr(worker.factory, "make_platform", lambda: object())
    for task in (worker.voice_enable, worker.voice_disable):
        with pytest.raises(Retry) as asked:
            task.apply(args=[str(uuid.uuid4()), str(uuid.uuid4())], throw=True)
        assert asked.value.when == worker.backoff(0)


def test_a_finished_outcome_is_returned_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domains.voice.provisioning import JobOutcome

    monkeypatch.setattr(worker, "_run", lambda coro: (coro.close(), JobOutcome.DONE)[1])
    monkeypatch.setattr(worker.factory, "tools_base_url", lambda: "https://tools.example.test")
    monkeypatch.setattr(worker.factory, "make_platform", lambda: object())
    result = worker.voice_enable.apply(args=[str(uuid.uuid4()), str(uuid.uuid4())])
    assert result.get() == "done"


def test_two_tasks_in_one_worker_process_do_not_trip_over_each_others_event_loops() -> None:
    """A worker runs each task in its own `asyncio.run` but keeps one process (and one module-level
    database engine and Redis client). Run two in a row, in a fresh process, against the real
    services: the second must not reuse connections that belong to the first task's dead loop."""
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import uuid
        from sqlalchemy import text
        from app import worker
        from app.db.session import session_factory
        from app.domains.voice.provisioning import JobOutcome
        from app.realtime.bus import bus

        async def touch():
            async with session_factory() as s:
                assert (await s.execute(text("SELECT 1"))).scalar() == 1
            await bus.publish("worker-smoke", {"ok": True})
            return JobOutcome.DONE

        assert worker._run(touch()) == JobOutcome.DONE
        assert worker._run(touch()) == JobOutcome.DONE
        print("ok")
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().endswith("ok")
