from uuid import uuid4

import pytest

from app.core.permissions import (
    Capability,
    CustomerActor,
    PermissionDeniedError,
    PlatformAdminActor,
    Role,
    StaffActor,
    assert_can,
    assert_can_write_own_tab,
    assert_is_platform_admin,
    can,
)


def make_staff(*roles_at_outlets: tuple[object, Role]) -> StaffActor:
    return StaffActor(actor_type="staff", user_id=uuid4(), roles=frozenset(roles_at_outlets))


def test_role_with_capability_is_allowed() -> None:
    outlet_id = uuid4()
    waiter = make_staff((outlet_id, Role.WAITER))
    assert_can(waiter, Capability.ADD_ORDER_LINES, outlet_id)  # does not raise


def test_role_without_capability_is_denied() -> None:
    outlet_id = uuid4()
    waiter = make_staff((outlet_id, Role.WAITER))
    with pytest.raises(PermissionDeniedError):
        assert_can(waiter, Capability.VOID_OR_DISCOUNT_LINE, outlet_id)


def test_role_at_a_different_outlet_does_not_grant_access() -> None:
    outlet_a, outlet_b = uuid4(), uuid4()
    manager_at_a = make_staff((outlet_a, Role.MANAGER))
    with pytest.raises(PermissionDeniedError):
        assert_can(manager_at_a, Capability.VOID_OR_DISCOUNT_LINE, outlet_b)


def test_non_staff_actor_is_denied_staff_capability() -> None:
    outlet_id = uuid4()
    customer = CustomerActor(actor_type="customer", tab_session_id=uuid4(), tab_id=uuid4())
    with pytest.raises(PermissionDeniedError):
        assert_can(customer, Capability.ADD_ORDER_LINES, outlet_id)


@pytest.mark.parametrize(
    ("role", "capability", "allowed"),
    [
        (Role.BAR, Capability.ADD_ORDER_LINES, False),
        (Role.KITCHEN, Capability.MARK_ITEM_SOLD_OUT, True),
        (Role.WAITER, Capability.VOID_OR_DISCOUNT_LINE, False),
        (Role.MANAGER, Capability.EDIT_MENU_AVAILABILITY, True),
        (Role.MANAGER, Capability.EDIT_MENU_FULL, False),
        (Role.OWNER, Capability.EDIT_MENU_FULL, True),
        (Role.MANAGER, Capability.EXPORT_INTEGRATIONS, False),
        (Role.OWNER, Capability.EXPORT_INTEGRATIONS, True),
        (Role.MANAGER, Capability.ENABLE_VOICE_AGENT, False),
        (Role.WAITER, Capability.ENABLE_VOICE_AGENT, False),
        (Role.OWNER, Capability.ENABLE_VOICE_AGENT, True),
        (Role.MANAGER, Capability.ACCEPT_VOICE_ORDERS, True),
        (Role.OWNER, Capability.ACCEPT_VOICE_ORDERS, True),
        (Role.WAITER, Capability.ACCEPT_VOICE_ORDERS, False),
        (Role.KITCHEN, Capability.ACCEPT_VOICE_ORDERS, False),
        (Role.MANAGER, Capability.MANAGE_WAITER_STAFF, True),
        (Role.MANAGER, Capability.MANAGE_ALL_STAFF, False),
        (Role.BAR, Capability.VIEW_MENU, True),
        (Role.WAITER, Capability.VIEW_OUTLET_SETTINGS, True),
        (Role.MANAGER, Capability.EDIT_OUTLET_SETTINGS, False),
        (Role.OWNER, Capability.EDIT_OUTLET_SETTINGS, True),
    ],
)
def test_capability_matrix_matches_spec(role: Role, capability: Capability, allowed: bool) -> None:
    outlet_id = uuid4()
    actor = make_staff((outlet_id, role))
    if allowed:
        assert_can(actor, capability, outlet_id)
    else:
        with pytest.raises(PermissionDeniedError):
            assert_can(actor, capability, outlet_id)


def test_customer_can_write_own_tab() -> None:
    tab_id = uuid4()
    customer = CustomerActor(actor_type="customer", tab_session_id=uuid4(), tab_id=tab_id)
    assert_can_write_own_tab(customer, tab_id)  # does not raise


def test_tab_session_for_tab_a_cannot_write_to_tab_b() -> None:
    tab_a, tab_b = uuid4(), uuid4()
    customer_on_tab_a = CustomerActor(actor_type="customer", tab_session_id=uuid4(), tab_id=tab_a)
    with pytest.raises(PermissionDeniedError):
        assert_can_write_own_tab(customer_on_tab_a, tab_b)


def test_non_customer_actor_cannot_use_the_customer_tab_path() -> None:
    outlet_id = uuid4()
    tab_id = uuid4()
    waiter = make_staff((outlet_id, Role.WAITER))
    with pytest.raises(PermissionDeniedError):
        assert_can_write_own_tab(waiter, tab_id)


def test_platform_admin_actor_passes_platform_admin_check() -> None:
    admin = PlatformAdminActor(actor_type="platform_admin", user_id=uuid4())
    assert_is_platform_admin(admin)  # does not raise


def test_staff_actor_fails_platform_admin_check() -> None:
    outlet_id = uuid4()
    owner = make_staff((outlet_id, Role.OWNER))
    with pytest.raises(PermissionDeniedError):
        assert_is_platform_admin(owner)


def test_can_is_the_non_raising_form_of_assert_can() -> None:
    outlet_id = uuid4()
    manager = make_staff((outlet_id, Role.MANAGER))
    assert can(manager, Capability.SET_PRICE_RULES, outlet_id) is True
    assert can(manager, Capability.EDIT_MENU_FULL, outlet_id) is False
