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
