from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.permissions import Role
from app.core.realtime import (
    SIGNAL_ASSIGNMENTS_CHANGED,
    SIGNAL_MENU_CHANGED,
    TAB_ENDING_EVENTS,
    Audience,
    may_receive,
    may_receive_signal,
    redact,
)

TAB, OTHER_TAB = uuid4(), uuid4()
MINE, THEIRS = uuid4(), uuid4()


def staff(*roles: Role, tables: tuple[object, ...] = ()) -> Audience:
    return Audience(tab_id=None, roles=frozenset(roles), assigned_tables=frozenset(tables))  # type: ignore[arg-type]


def test_a_guest_sees_every_event_on_their_own_tab_and_nothing_else() -> None:
    guest = Audience(tab_id=TAB, roles=frozenset())
    assert guest.is_guest
    for event in ("opened", "line_added", "service_requested", "line_voided", "closed"):
        assert may_receive(guest, event, TAB)
        assert not may_receive(guest, event, OTHER_TAB)
        assert not may_receive(guest, event, OTHER_TAB, [MINE])


@pytest.mark.parametrize("role", [Role.MANAGER, Role.OWNER])
def test_managers_and_owners_see_every_table(role: Role) -> None:
    for event in ("opened", "service_requested", "line_disputed", "order_placed"):
        assert may_receive(staff(role), event, TAB, [THEIRS])
        assert may_receive(staff(role), event, TAB)


def test_a_waiter_sees_only_events_at_their_assigned_tables() -> None:
    waiter = staff(Role.WAITER, tables=(MINE,))
    for event in ("opened", "service_requested", "bill_requested", "line_disputed"):
        assert may_receive(waiter, event, TAB, [MINE])
        assert not may_receive(waiter, event, TAB, [THEIRS])
        assert not may_receive(waiter, event, TAB, [None])
        assert not may_receive(waiter, event, TAB)


def test_a_transfer_reaches_the_waiters_at_both_tables() -> None:
    from_table = staff(Role.WAITER, tables=(THEIRS,))
    to_table = staff(Role.WAITER, tables=(MINE,))
    for waiter in (from_table, to_table):
        assert may_receive(waiter, "transferred", TAB, [MINE, THEIRS])


@pytest.mark.parametrize("role", [Role.KITCHEN, Role.BAR])
def test_kitchen_and_bar_see_only_production_events_at_any_table(role: Role) -> None:
    for event in (
        "line_added",
        "order_placed",
        "order_accepted",
        "order_cancelled",
        "ticket_started",
        "ticket_ready",
        "ticket_recalled",
        "order_served",
    ):
        assert may_receive(staff(role), event, TAB, [THEIRS])
    for event in ("service_requested", "bill_requested", "line_voided", "opened", "confirmed"):
        assert not may_receive(staff(role), event, TAB, [THEIRS])


def test_roles_are_additive() -> None:
    both = staff(Role.KITCHEN, Role.WAITER, tables=(MINE,))
    assert may_receive(both, "service_requested", TAB, [MINE])
    assert not may_receive(both, "service_requested", TAB, [THEIRS])
    assert may_receive(both, "order_placed", TAB, [THEIRS])


def test_signals() -> None:
    guest = Audience(tab_id=TAB, roles=frozenset())
    assert may_receive_signal(guest, SIGNAL_MENU_CHANGED)
    assert not may_receive_signal(guest, SIGNAL_ASSIGNMENTS_CHANGED)
    assert may_receive_signal(staff(Role.WAITER), SIGNAL_ASSIGNMENTS_CHANGED)
    assert may_receive_signal(staff(Role.KITCHEN), SIGNAL_MENU_CHANGED)


def test_kitchen_never_sees_money() -> None:
    payload = {
        "item": "Paneer Tikka",
        "qty": 2,
        "unit_price_paise": 32000,
        "line_total_paise": 64000,
        "total_paise": 64000,
        "modifiers": ["Hot"],
    }
    assert redact(staff(Role.KITCHEN), payload) == {
        "item": "Paneer Tikka",
        "qty": 2,
        "modifiers": ["Hot"],
    }
    assert redact(staff(Role.BAR), payload) == redact(staff(Role.KITCHEN), payload)


def test_guests_and_front_of_house_get_the_full_payload() -> None:
    payload = {"item": "x", "unit_price_paise": 1}
    assert redact(Audience(tab_id=TAB, roles=frozenset()), payload) == payload
    assert redact(staff(Role.WAITER), payload) == payload
    assert redact(staff(Role.KITCHEN, Role.MANAGER), payload) == payload


def test_tab_ending_events() -> None:
    assert {"closed", "voided"} == TAB_ENDING_EVENTS
