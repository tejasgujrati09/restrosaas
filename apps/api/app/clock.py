"""The one place the API reads the wall clock, so tests can move time
(the 60-second undo window and price-rule boundaries depend on it)."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
