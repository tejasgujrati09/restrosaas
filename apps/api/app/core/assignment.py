"""Which waiter takes an unassigned table (docs/DECISIONS.md "Table assignment: bulk and
automatic"). Pure functions: the database work (who is eligible, how loaded) is in
`app.domains.tab.auto_assign`, which calls `choose` under the outlet row lock."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Strategy(StrEnum):
    NEAREST = "nearest"
    LEAST_LOADED = "least_loaded"
    ROTATION = "rotation"


@dataclass(frozen=True)
class WaiterLoad:
    user_id: UUID
    # Assigned tables with a guest at them right now, and rounds still being made or carried.
    active_tables: int
    active_orders: int
    # Tables this waiter serves in the same zone as the new order's table.
    zone_tables: int


def _load_key(w: WaiterLoad) -> tuple[int, int, str]:
    return (w.active_tables, w.active_orders, str(w.user_id))


def least_loaded(waiters: Sequence[WaiterLoad]) -> UUID | None:
    """Fewest tables with guests, then fewest rounds in flight, then a stable order."""
    return min(waiters, key=_load_key).user_id if waiters else None


def nearest(waiters: Sequence[WaiterLoad]) -> UUID | None:
    """There is no floor plan, so "near" means already serving the table's zone: the waiter
    with the most tables in it. If nobody serves the zone, the least loaded waiter."""
    if not waiters:
        return None
    in_zone = [w for w in waiters if w.zone_tables > 0]
    if not in_zone:
        return least_loaded(waiters)
    best = max(w.zone_tables for w in in_zone)
    return least_loaded([w for w in in_zone if w.zone_tables == best])


def rotation(waiters: Sequence[WaiterLoad], last_assigned: UUID | None) -> UUID | None:
    """The next waiter after the one who had the last turn, in a fixed order. A waiter who
    has since left the eligible list is skipped over, not stuck on."""
    if not waiters:
        return None
    order = sorted(str(w.user_id) for w in waiters)
    if last_assigned is None:
        return UUID(order[0])
    following = [u for u in order if u > str(last_assigned)]
    return UUID(following[0] if following else order[0])


def choose(
    strategy: Strategy, waiters: Sequence[WaiterLoad], last_assigned: UUID | None
) -> UUID | None:
    if strategy == Strategy.ROTATION:
        return rotation(waiters, last_assigned)
    if strategy == Strategy.NEAREST:
        return nearest(waiters)
    return least_loaded(waiters)
