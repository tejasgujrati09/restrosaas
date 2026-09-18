"""Tab and Order state machines — the single source of truth for legal
transitions (docs/SPEC.md §8). Route handlers call `transition_tab` /
`transition_order`; an illegal transition raises `IllegalTransitionError`,
which the API layer maps to HTTP 409 with the current state.
"""

from __future__ import annotations

from enum import StrEnum


class TabState(StrEnum):
    OPEN = "open"
    BILL_REQUESTED = "bill_requested"
    CLOSED = "closed"
    VOIDED = "voided"


class OrderState(StrEnum):
    PLACED = "placed"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    READY = "ready"
    SERVED = "served"
    CANCELLED = "cancelled"
    # Phase 3 delivery hooks (docs/SPEC.md §8) — do not remove.
    DISPATCHED = "dispatched"
    DELIVERED = "delivered"


class IllegalTransitionError(Exception):
    def __init__(self, entity: str, current: StrEnum, target: StrEnum) -> None:
        self.entity = entity
        self.current = current
        self.target = target
        super().__init__(f"illegal {entity} transition: {current} -> {target}")


# open -> open covers "orders added / transferred / merged": the tab stays
# open, but it is still a transition a caller may legally request.
_TAB_TRANSITIONS: dict[TabState, frozenset[TabState]] = {
    TabState.OPEN: frozenset({TabState.OPEN, TabState.BILL_REQUESTED, TabState.VOIDED}),
    TabState.BILL_REQUESTED: frozenset({TabState.OPEN, TabState.CLOSED}),
    TabState.CLOSED: frozenset(),
    TabState.VOIDED: frozenset(),
}

_ORDER_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.PLACED: frozenset({OrderState.ACCEPTED, OrderState.CANCELLED}),
    OrderState.ACCEPTED: frozenset({OrderState.PREPARING, OrderState.CANCELLED}),
    OrderState.PREPARING: frozenset({OrderState.READY}),
    OrderState.READY: frozenset({OrderState.SERVED, OrderState.DISPATCHED}),
    OrderState.SERVED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.DISPATCHED: frozenset({OrderState.DELIVERED}),
    OrderState.DELIVERED: frozenset(),
}


def can_transition_tab(current: TabState, target: TabState) -> bool:
    return target in _TAB_TRANSITIONS[current]


def transition_tab(current: TabState, target: TabState) -> TabState:
    if not can_transition_tab(current, target):
        raise IllegalTransitionError("tab", current, target)
    return target


def can_transition_order(current: OrderState, target: OrderState) -> bool:
    return target in _ORDER_TRANSITIONS[current]


def transition_order(current: OrderState, target: OrderState) -> OrderState:
    if not can_transition_order(current, target):
        raise IllegalTransitionError("order", current, target)
    return target


_CUSTOMER_CANCEL_WINDOW_SECONDS = 60


def can_customer_cancel_order_line(order_status: OrderState, seconds_since_placed: float) -> bool:
    """A customer may cancel a line only within 60s of placing and only
    before the round is accepted (docs/SPEC.md §8). Any later cancellation is
    a manager void with a reason, not this path.
    """
    if order_status != OrderState.PLACED:
        return False
    return seconds_since_placed <= _CUSTOMER_CANCEL_WINDOW_SECONDS
