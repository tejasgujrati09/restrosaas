"""Who may see which tab event on the live channel (docs/SPEC.md §6, and
CLAUDE.md §1.3: staff see only what their role needs, enforced server-side).

Pure. The gateway calls `may_receive` for every message and `redact` for what
it forwards, so a client that ignores its own filters still learns nothing extra.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.permissions import Role

# Everything that changes what a kitchen or bar must make.
_PRODUCTION_EVENTS = frozenset({"line_added", "order_placed", "order_accepted", "order_cancelled"})
# After these the guest's session is over; the gateway closes their socket.
TAB_ENDING_EVENTS = frozenset({"closed", "voided"})


@dataclass(frozen=True)
class Audience:
    """One connected client. A guest is scoped to a single tab; staff to roles at the outlet."""

    tab_id: UUID | None
    roles: frozenset[Role]

    @property
    def is_guest(self) -> bool:
        return self.tab_id is not None


def may_receive(audience: Audience, event: str, tab_id: UUID) -> bool:
    if audience.is_guest:
        return audience.tab_id == tab_id
    if audience.roles & {Role.WAITER, Role.MANAGER, Role.OWNER}:
        return True
    return event in _PRODUCTION_EVENTS


def redact(audience: Audience, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Kitchen and bar see what to make, never what it costs."""
    if audience.is_guest or audience.roles & {Role.WAITER, Role.MANAGER, Role.OWNER}:
        return dict(payload)
    return {k: v for k, v in payload.items() if "price" not in k and "total" not in k}
