"""The waiter's table map: what colour a table is (docs/UI-FLOWS.md §2)."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum


class TableState(StrEnum):
    EMPTY = "empty"
    SEATED = "seated"
    ORDER_PENDING = "order_pending"
    BILL_REQUESTED = "bill_requested"


_IN_FLIGHT = ("placed", "accepted", "preparing", "ready")


def table_state(tab_status: str | None, round_statuses: Sequence[str]) -> TableState:
    """No live tab: empty. Bill requested wins over everything else. Otherwise a table with
    a round still on its way to the guest (placed through ready) needs attention;
    one whose rounds are all served or cancelled is simply seated."""
    if tab_status not in ("open", "bill_requested"):
        return TableState.EMPTY
    if tab_status == "bill_requested":
        return TableState.BILL_REQUESTED
    if any(s in _IN_FLIGHT for s in round_statuses):
        return TableState.ORDER_PENDING
    return TableState.SEATED
