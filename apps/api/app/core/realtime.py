"""Who may see which tab event on the live channel (docs/SPEC.md §6, and
CLAUDE.md §1.3: staff see only what their role needs, enforced server-side).

Pure. The gateway calls `may_receive` for every message and `redact` for what
it forwards, so a client that ignores its own filters still learns nothing extra.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.permissions import Role

# Everything that changes what a kitchen or bar must make, or has made.
_PRODUCTION_EVENTS = frozenset(
    {
        "line_added",
        "order_placed",
        "order_accepted",
        "order_cancelled",
        "order_preparing",
        "order_ready",
        "order_served",
        "line_served",
        "ticket_started",
        "ticket_ready",
        "ticket_recalled",
    }
)
_FRONT_OF_HOUSE = frozenset({Role.WAITER, Role.MANAGER, Role.OWNER})
_SEES_EVERY_TABLE = frozenset({Role.MANAGER, Role.OWNER})
# After these the guest's session is over; the gateway closes their socket.
TAB_ENDING_EVENTS = frozenset({"closed", "voided"})

# Signals are outlet-wide nudges with no tab attached.
SIGNAL_MENU_CHANGED = "menu_changed"
SIGNAL_ASSIGNMENTS_CHANGED = "assignments_changed"


@dataclass(frozen=True)
class Audience:
    """One connected client. A guest is scoped to a single tab; staff to roles at the
    outlet. `assigned_tables` is the waiter's own tables; managers and owners see all."""

    tab_id: UUID | None
    roles: frozenset[Role]
    assigned_tables: frozenset[UUID] = frozenset()

    @property
    def is_guest(self) -> bool:
        return self.tab_id is not None


def may_receive(
    audience: Audience, event: str, tab_id: UUID, table_ids: Iterable[UUID | None] = ()
) -> bool:
    """`table_ids` are the tables the event concerns: where the tab is now and, for a
    transfer, where it came from, so both waiters hear about it."""
    if audience.is_guest:
        return audience.tab_id == tab_id
    if audience.roles & _SEES_EVERY_TABLE:
        return True
    if Role.WAITER in audience.roles and any(
        t is not None and t in audience.assigned_tables for t in table_ids
    ):
        return True
    return bool(audience.roles & {Role.KITCHEN, Role.BAR}) and event in _PRODUCTION_EVENTS


def may_receive_signal(audience: Audience, name: str) -> bool:
    if name == SIGNAL_MENU_CHANGED:
        return True
    return not audience.is_guest


def redact(audience: Audience, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Kitchen and bar see what to make, never what it costs."""
    if audience.is_guest or audience.roles & _FRONT_OF_HOUSE:
        return dict(payload)
    return {k: v for k, v in payload.items() if "price" not in k and "total" not in k}
