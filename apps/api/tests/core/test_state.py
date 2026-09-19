import pytest

from app.core.state import (
    IllegalTransitionError,
    OrderState,
    TabState,
    can_customer_cancel_order_line,
    can_transition_order,
    can_transition_tab,
    transition_order,
    transition_tab,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TabState.OPEN, TabState.OPEN),
        (TabState.OPEN, TabState.BILL_REQUESTED),
        (TabState.OPEN, TabState.VOIDED),
        (TabState.BILL_REQUESTED, TabState.OPEN),
        (TabState.BILL_REQUESTED, TabState.CLOSED),
    ],
)
def test_legal_tab_transitions(current: TabState, target: TabState) -> None:
    assert can_transition_tab(current, target) is True
    assert transition_tab(current, target) == target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TabState.CLOSED, TabState.OPEN),
        (TabState.VOIDED, TabState.OPEN),
        (TabState.BILL_REQUESTED, TabState.VOIDED),
        (TabState.OPEN, TabState.CLOSED),
    ],
)
def test_illegal_tab_transitions_raise_409able_error(current: TabState, target: TabState) -> None:
    assert can_transition_tab(current, target) is False
    with pytest.raises(IllegalTransitionError) as exc_info:
        transition_tab(current, target)
    assert exc_info.value.entity == "tab"
    assert exc_info.value.current == current
    assert exc_info.value.target == target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OrderState.PLACED, OrderState.ACCEPTED),
        (OrderState.PLACED, OrderState.CANCELLED),
        (OrderState.ACCEPTED, OrderState.PREPARING),
        (OrderState.ACCEPTED, OrderState.CANCELLED),
        (OrderState.PREPARING, OrderState.READY),
        (OrderState.READY, OrderState.SERVED),
        (OrderState.READY, OrderState.DISPATCHED),
        (OrderState.DISPATCHED, OrderState.DELIVERED),
    ],
)
def test_legal_order_transitions(current: OrderState, target: OrderState) -> None:
    assert can_transition_order(current, target) is True
    assert transition_order(current, target) == target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OrderState.SERVED, OrderState.PREPARING),
        (OrderState.DELIVERED, OrderState.DISPATCHED),
        (OrderState.CANCELLED, OrderState.PLACED),
        (OrderState.PLACED, OrderState.PREPARING),
        (OrderState.PLACED, OrderState.READY),
    ],
)
def test_illegal_order_transitions_raise_409able_error(
    current: OrderState, target: OrderState
) -> None:
    assert can_transition_order(current, target) is False
    with pytest.raises(IllegalTransitionError) as exc_info:
        transition_order(current, target)
    assert exc_info.value.entity == "order"


def test_customer_can_cancel_within_60s_of_placing() -> None:
    assert can_customer_cancel_order_line(OrderState.PLACED, 0) is True
    assert can_customer_cancel_order_line(OrderState.PLACED, 60) is True


def test_customer_cannot_cancel_after_60s() -> None:
    assert can_customer_cancel_order_line(OrderState.PLACED, 60.1) is False


def test_customer_cannot_cancel_once_accepted() -> None:
    assert can_customer_cancel_order_line(OrderState.ACCEPTED, 1) is False


@pytest.mark.parametrize(
    ("status", "seconds", "due"),
    [
        (OrderState.PLACED, 59.9, False),
        (OrderState.PLACED, 60, False),
        (OrderState.PLACED, 60.1, True),
        (OrderState.ACCEPTED, 600, False),
        (OrderState.CANCELLED, 600, False),
    ],
)
def test_auto_accept_is_due_only_after_the_undo_window(
    status: OrderState, seconds: float, due: bool
) -> None:
    from app.core.state import order_auto_accept_due

    assert order_auto_accept_due(status, seconds) is due


def test_undo_and_auto_accept_never_both_hold() -> None:
    from app.core.state import order_auto_accept_due

    for tenths in range(0, 1200):
        seconds = tenths / 10
        assert not (
            can_customer_cancel_order_line(OrderState.PLACED, seconds)
            and order_auto_accept_due(OrderState.PLACED, seconds)
        )


def test_ticket_transitions() -> None:
    from app.core.state import TicketState, transition_ticket

    legal = [
        (TicketState.QUEUED, TicketState.PREPARING),
        (TicketState.QUEUED, TicketState.CANCELLED),
        (TicketState.PREPARING, TicketState.READY),
        (TicketState.PREPARING, TicketState.CANCELLED),
        (TicketState.READY, TicketState.PREPARING),  # recall
        (TicketState.READY, TicketState.BUMPED),
    ]
    for current, target in legal:
        assert transition_ticket(current, target) == target
    illegal = [
        (TicketState.QUEUED, TicketState.READY),
        (TicketState.READY, TicketState.CANCELLED),
        (TicketState.BUMPED, TicketState.PREPARING),
        (TicketState.CANCELLED, TicketState.QUEUED),
    ]
    for current, target in illegal:
        with pytest.raises(IllegalTransitionError):
            transition_ticket(current, target)


def test_a_ticket_can_start_only_after_the_undo_window() -> None:
    from app.core.state import ticket_startable

    assert not ticket_startable(OrderState.PLACED)
    assert not ticket_startable(OrderState.CANCELLED)
    for status in (OrderState.ACCEPTED, OrderState.PREPARING, OrderState.READY, OrderState.SERVED):
        assert ticket_startable(status)


@pytest.mark.parametrize(
    ("current", "lines", "expected"),
    [
        (OrderState.ACCEPTED, ["accepted", "accepted"], OrderState.ACCEPTED),
        (OrderState.ACCEPTED, ["preparing", "accepted"], OrderState.PREPARING),
        (OrderState.ACCEPTED, ["ready", "accepted"], OrderState.PREPARING),
        (OrderState.PREPARING, ["ready", "preparing"], OrderState.PREPARING),
        (OrderState.PREPARING, ["ready", "ready"], OrderState.READY),
        (OrderState.PREPARING, ["served", "ready"], OrderState.READY),
        (OrderState.PREPARING, ["served", "preparing"], OrderState.PREPARING),
        (OrderState.READY, ["served", "served"], OrderState.SERVED),
        (OrderState.READY, ["served", "ready"], OrderState.READY),
        # A recall sends a line back to preparing; the round does not step backwards.
        (OrderState.READY, ["served", "preparing"], OrderState.READY),
        (OrderState.PREPARING, ["ready", "cancelled"], OrderState.READY),
        (OrderState.PREPARING, ["cancelled", "voided"], OrderState.PREPARING),
        (OrderState.PLACED, ["placed"], OrderState.PLACED),
        (OrderState.CANCELLED, ["served"], OrderState.CANCELLED),
        (OrderState.DISPATCHED, ["served"], OrderState.DISPATCHED),
    ],
)
def test_round_status_follows_its_lines(
    current: OrderState, lines: list[str], expected: OrderState
) -> None:
    from app.core.state import derive_order_status

    assert derive_order_status(current, lines) == expected
