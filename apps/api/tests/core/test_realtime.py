from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.permissions import Role
from app.core.realtime import TAB_ENDING_EVENTS, Audience, may_receive, redact

TAB, OTHER_TAB = uuid4(), uuid4()


def staff(*roles: Role) -> Audience:
    return Audience(tab_id=None, roles=frozenset(roles))


def test_a_guest_sees_every_event_on_their_own_tab_and_nothing_else() -> None:
    guest = Audience(tab_id=TAB, roles=frozenset())
    assert guest.is_guest
    for event in ("opened", "line_added", "service_requested", "line_voided", "closed"):
        assert may_receive(guest, event, TAB)
        assert not may_receive(guest, event, OTHER_TAB)


@pytest.mark.parametrize("role", [Role.WAITER, Role.MANAGER, Role.OWNER])
def test_front_of_house_sees_all_events_at_the_outlet(role: Role) -> None:
    for event in ("opened", "service_requested", "bill_requested", "line_voided", "order_placed"):
        assert may_receive(staff(role), event, TAB)


@pytest.mark.parametrize("role", [Role.KITCHEN, Role.BAR])
def test_kitchen_and_bar_see_only_production_events(role: Role) -> None:
    for event in ("line_added", "order_placed", "order_accepted", "order_cancelled"):
        assert may_receive(staff(role), event, TAB)
    for event in ("service_requested", "bill_requested", "line_voided", "opened", "confirmed"):
        assert not may_receive(staff(role), event, TAB)


def test_roles_are_additive() -> None:
    assert may_receive(staff(Role.KITCHEN, Role.WAITER), "service_requested", TAB)


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
