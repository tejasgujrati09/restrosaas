"""Tab and Order state machines — the single source of truth for legal
transitions (docs/SPEC.md §8). Route handlers call `transition_tab` /
`transition_order`; an illegal transition raises `IllegalTransitionError`,
which the API layer maps to HTTP 409 with the current state.
"""

from __future__ import annotations

from collections.abc import Sequence
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


def order_auto_accept_due(order_status: OrderState, seconds_since_placed: float) -> bool:
    """In auto mode a round is accepted once the customer's undo window has
    closed (docs/DECISIONS.md "Milestone 3 choices"). Strictly greater, so the
    two rules never both hold at the same instant."""
    if order_status != OrderState.PLACED:
        return False
    return seconds_since_placed > _CUSTOMER_CANCEL_WINDOW_SECONDS


CUSTOMER_UNDO_WINDOW_SECONDS = _CUSTOMER_CANCEL_WINDOW_SECONDS


class TicketState(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    READY = "ready"
    BUMPED = "bumped"
    CANCELLED = "cancelled"


# ready -> preparing is "recall": the last bumped ticket comes back while nothing on it is served.
_TICKET_TRANSITIONS: dict[TicketState, frozenset[TicketState]] = {
    TicketState.QUEUED: frozenset({TicketState.PREPARING, TicketState.CANCELLED}),
    TicketState.PREPARING: frozenset({TicketState.READY, TicketState.CANCELLED}),
    TicketState.READY: frozenset({TicketState.PREPARING, TicketState.BUMPED}),
    TicketState.BUMPED: frozenset(),
    TicketState.CANCELLED: frozenset(),
}


def transition_ticket(current: TicketState, target: TicketState) -> TicketState:
    if target not in _TICKET_TRANSITIONS[current]:
        raise IllegalTransitionError("ticket", current, target)
    return target


def ticket_startable(order_status: OrderState) -> bool:
    """A ticket shows in the queue the moment a round is placed, but the kitchen may
    only start it once the guest's undo window has closed and the round is accepted."""
    return order_status not in (OrderState.PLACED, OrderState.CANCELLED)


_ORDER_RANK = {
    OrderState.PLACED: 0,
    OrderState.ACCEPTED: 1,
    OrderState.PREPARING: 2,
    OrderState.READY: 3,
    OrderState.SERVED: 4,
}


def derive_order_status(current: OrderState, line_statuses: Sequence[str]) -> OrderState:
    """A round's status follows its active lines: preparing once any line is being made,
    ready when every line is ready or served, served when all are served. It never moves
    backwards (a recalled ticket returns a line to preparing without undoing 'ready' for
    lines already served), and rounds outside the dine-in path are left alone."""
    if current not in _ORDER_RANK:
        return current
    active = [s for s in line_statuses if s not in ("cancelled", "voided")]
    if not active:
        return current
    if all(s == "served" for s in active):
        target = OrderState.SERVED
    elif all(s in ("ready", "served") for s in active):
        target = OrderState.READY
    elif any(s in ("preparing", "ready", "served") for s in active):
        target = OrderState.PREPARING
    else:
        return current
    return target if _ORDER_RANK[target] > _ORDER_RANK[current] else current


class VoiceState(StrEnum):
    """The owner's phone ordering agent for an outlet. No row at all is "off"."""

    ENABLE_REQUESTED = "enable_requested"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    PROVISIONING_FAILED = "provisioning_failed"
    DISABLE_REQUESTED = "disable_requested"
    DEPROVISIONING = "deprovisioning"
    DISABLED = "disabled"
    DEPROVISIONING_FAILED = "deprovisioning_failed"


# provisioning -> enable_requested and deprovisioning -> disable_requested are "try again
# shortly" after a transient platform error; the job is queued again with a delay.
# Disabling from enable_requested/provisioning/provisioning_failed is how an owner (or an
# admin revoking the allowance) cancels a setup that has not finished.
_VOICE_TRANSITIONS: dict[VoiceState, frozenset[VoiceState]] = {
    VoiceState.ENABLE_REQUESTED: frozenset({VoiceState.PROVISIONING, VoiceState.DISABLE_REQUESTED}),
    VoiceState.PROVISIONING: frozenset(
        {
            VoiceState.ACTIVE,
            VoiceState.PROVISIONING_FAILED,
            VoiceState.ENABLE_REQUESTED,
            VoiceState.DISABLE_REQUESTED,
        }
    ),
    VoiceState.ACTIVE: frozenset({VoiceState.DISABLE_REQUESTED}),
    VoiceState.PROVISIONING_FAILED: frozenset(
        {VoiceState.ENABLE_REQUESTED, VoiceState.DISABLE_REQUESTED}
    ),
    VoiceState.DISABLE_REQUESTED: frozenset({VoiceState.DEPROVISIONING}),
    VoiceState.DEPROVISIONING: frozenset(
        {
            VoiceState.DISABLED,
            VoiceState.DEPROVISIONING_FAILED,
            VoiceState.DISABLE_REQUESTED,
        }
    ),
    VoiceState.DISABLED: frozenset({VoiceState.ENABLE_REQUESTED}),
    VoiceState.DEPROVISIONING_FAILED: frozenset({VoiceState.DISABLE_REQUESTED}),
}

# States in which a job is queued or running; the owner is told "setting up" or "turning off".
VOICE_IN_FLIGHT = frozenset(
    {
        VoiceState.ENABLE_REQUESTED,
        VoiceState.PROVISIONING,
        VoiceState.DISABLE_REQUESTED,
        VoiceState.DEPROVISIONING,
    }
)


def can_transition_voice(current: VoiceState, target: VoiceState) -> bool:
    return target in _VOICE_TRANSITIONS[current]


def transition_voice(current: VoiceState, target: VoiceState) -> VoiceState:
    if not can_transition_voice(current, target):
        raise IllegalTransitionError("voice agent", current, target)
    return target
