"""How the owner's Orders screen groups and acts on orders. Pure: no new status system, just
the existing `OrderState` values gathered into the tabs an owner thinks in, and which of the
existing actions are worth offering. The endpoints behind each action still enforce the real
rules and roles; offering an action here never grants it."""

from __future__ import annotations

from enum import StrEnum

from app.core.state import OrderState


class OrderGroup(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


_GROUP_STATES: dict[OrderGroup, frozenset[OrderState]] = {
    OrderGroup.NEW: frozenset({OrderState.PLACED}),
    OrderGroup.IN_PROGRESS: frozenset({OrderState.ACCEPTED, OrderState.PREPARING}),
    OrderGroup.READY: frozenset({OrderState.READY, OrderState.DISPATCHED}),
    OrderGroup.COMPLETED: frozenset({OrderState.SERVED, OrderState.DELIVERED}),
    OrderGroup.CANCELLED: frozenset({OrderState.CANCELLED}),
}

# Orders that still need someone to act. Used to warn about ones left over from before the
# date the owner is looking at.
OPEN_STATES = (
    _GROUP_STATES[OrderGroup.NEW]
    | _GROUP_STATES[OrderGroup.IN_PROGRESS]
    | _GROUP_STATES[OrderGroup.READY]
)


def group_of(status: str) -> OrderGroup:
    state = OrderState(status)
    return next(group for group, states in _GROUP_STATES.items() if state in states)


def statuses_in(group: OrderGroup) -> list[str]:
    return sorted(s.value for s in _GROUP_STATES[group])


class OrderAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    SERVE = "serve"


def available_actions(
    status: str, source: str, *, can_accept_voice: bool, can_serve: bool
) -> list[OrderAction]:
    """What the owner may be offered for an order in this status.

    A phone order waits for a person to accept it (accept or reject); a QR or waiter order is
    accepted by the system once the guest's undo window closes, so there is nothing to offer.
    Preparing and ready belong to the kitchen and bar, so they are not offered here. Once a
    round is ready it can be marked served."""
    state = OrderState(status)
    actions: list[OrderAction] = []
    if state == OrderState.PLACED and source == "voice" and can_accept_voice:
        actions += [OrderAction.ACCEPT, OrderAction.REJECT]
    if state == OrderState.READY and can_serve:
        actions.append(OrderAction.SERVE)
    return actions
