import pytest

from app.core.order_view import (
    OPEN_STATES,
    OrderAction,
    OrderGroup,
    available_actions,
    group_of,
    statuses_in,
)
from app.core.state import OrderState


def test_every_real_status_belongs_to_exactly_one_tab() -> None:
    seen: dict[str, OrderGroup] = {}
    for group in OrderGroup:
        for status in statuses_in(group):
            assert status not in seen
            seen[status] = group
    assert set(seen) == {s.value for s in OrderState}
    for status, group in seen.items():
        assert group_of(status) == group


@pytest.mark.parametrize(
    ("status", "group"),
    [
        ("placed", OrderGroup.NEW),
        ("accepted", OrderGroup.IN_PROGRESS),
        ("preparing", OrderGroup.IN_PROGRESS),
        ("ready", OrderGroup.READY),
        ("served", OrderGroup.COMPLETED),
        ("cancelled", OrderGroup.CANCELLED),
    ],
)
def test_the_tabs_an_owner_expects(status: str, group: OrderGroup) -> None:
    assert group_of(status) == group


def test_open_orders_are_everything_not_finished() -> None:
    assert {s.value for s in OPEN_STATES} == {
        "placed",
        "accepted",
        "preparing",
        "ready",
        "dispatched",
    }


def test_a_phone_order_waiting_for_a_person_offers_accept_and_reject_only_to_who_may() -> None:
    assert available_actions("placed", "voice", can_accept_voice=True, can_serve=True) == [
        OrderAction.ACCEPT,
        OrderAction.REJECT,
    ]
    assert available_actions("placed", "voice", can_accept_voice=False, can_serve=True) == []


def test_a_qr_or_waiter_order_is_accepted_by_the_system_so_nothing_is_offered() -> None:
    for source in ("customer", "waiter", "aggregator"):
        assert available_actions("placed", source, can_accept_voice=True, can_serve=True) == []


def test_kitchen_steps_are_not_offered_but_a_ready_round_can_be_served() -> None:
    for status in ("accepted", "preparing", "served", "cancelled"):
        assert available_actions(status, "voice", can_accept_voice=True, can_serve=True) == []
    assert available_actions("ready", "customer", can_accept_voice=True, can_serve=True) == [
        OrderAction.SERVE
    ]
    assert available_actions("ready", "customer", can_accept_voice=True, can_serve=False) == []
