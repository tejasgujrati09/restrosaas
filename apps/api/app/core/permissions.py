"""The single permission matrix, mirroring docs/SPEC.md §6. Route handlers
call `assert_can` (staff, outlet-scoped), `assert_can_write_own_tab`
(unauthenticated guests, scoped to their own TabSession — see
docs/DECISIONS.md "Customer actor model"), or `assert_is_platform_admin`.
The UI hiding a button is never a substitute for calling one of these.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID


class Role(StrEnum):
    """Mirrors `StaffRole.role` (docs/SPEC.md §7.1)."""

    WAITER = "waiter"
    KITCHEN = "kitchen"
    BAR = "bar"
    MANAGER = "manager"
    OWNER = "owner"


class Capability(StrEnum):
    VIEW_TABLES_AND_TABS = "view_tables_and_tabs"
    # Not in docs/SPEC.md §6; see docs/DECISIONS.md "Milestone 2 choices".
    VIEW_MENU = "view_menu"
    VIEW_OUTLET_SETTINGS = "view_outlet_settings"
    EDIT_OUTLET_SETTINGS = "edit_outlet_settings"
    ADD_ORDER_LINES = "add_order_lines"
    MARK_ORDER_SERVED = "mark_order_served"
    MARK_ORDER_PREPARING = "mark_order_preparing"
    MARK_ORDER_READY = "mark_order_ready"
    MARK_ITEM_SOLD_OUT = "mark_item_sold_out"
    OPEN_TRANSFER_MERGE_TABS = "open_transfer_merge_tabs"
    CLOSE_TAB_RECORD_PAYMENT = "close_tab_record_payment"
    VOID_OR_DISCOUNT_LINE = "void_or_discount_line"
    APPROVE_LIQUOR_LINE = "approve_liquor_line"
    REOPEN_CLOSED_BILL = "reopen_closed_bill"
    EDIT_MENU_AVAILABILITY = "edit_menu_availability"
    EDIT_MENU_FULL = "edit_menu_full"
    SET_PRICE_RULES = "set_price_rules"
    MANAGE_WAITER_STAFF = "manage_waiter_staff"
    MANAGE_ALL_STAFF = "manage_all_staff"
    GENERATE_TABLE_QRS = "generate_table_qrs"
    DAY_CLOSE_AND_REPORTS = "day_close_and_reports"
    EXPORT_INTEGRATIONS = "export_integrations"
    MANAGE_SUBSCRIPTION_BILLING = "manage_subscription_billing"
    # Not in docs/SPEC.md §6; see docs/DECISIONS.md "Owner analytics".
    VIEW_ANALYTICS = "view_analytics"
    EDIT_EXPECTED_PREP = "edit_expected_prep"


# Capability -> the outlet-scoped staff roles that hold it. A role missing
# from a set is a hard "-" in the docs/SPEC.md §6 table. Owner/Manager are
# listed explicitly everywhere Waiter is (rather than derived via hierarchy)
# because that is what the table itself shows; SPEC §6's "roles are additive"
# note falls out of this automatically.
CAPABILITY_MATRIX: dict[Capability, frozenset[Role]] = {
    Capability.VIEW_MENU: frozenset(Role),
    Capability.VIEW_OUTLET_SETTINGS: frozenset(Role),
    Capability.EDIT_OUTLET_SETTINGS: frozenset({Role.OWNER}),
    Capability.VIEW_TABLES_AND_TABS: frozenset({Role.WAITER, Role.MANAGER, Role.OWNER}),
    Capability.ADD_ORDER_LINES: frozenset({Role.WAITER, Role.MANAGER, Role.OWNER}),
    Capability.MARK_ORDER_SERVED: frozenset({Role.WAITER, Role.MANAGER, Role.OWNER}),
    Capability.MARK_ORDER_PREPARING: frozenset({Role.KITCHEN, Role.BAR, Role.MANAGER, Role.OWNER}),
    Capability.MARK_ORDER_READY: frozenset({Role.KITCHEN, Role.BAR, Role.MANAGER, Role.OWNER}),
    Capability.MARK_ITEM_SOLD_OUT: frozenset({Role.KITCHEN, Role.BAR, Role.MANAGER, Role.OWNER}),
    Capability.OPEN_TRANSFER_MERGE_TABS: frozenset({Role.WAITER, Role.MANAGER, Role.OWNER}),
    Capability.CLOSE_TAB_RECORD_PAYMENT: frozenset({Role.WAITER, Role.MANAGER, Role.OWNER}),
    Capability.VOID_OR_DISCOUNT_LINE: frozenset({Role.MANAGER, Role.OWNER}),
    Capability.APPROVE_LIQUOR_LINE: frozenset({Role.MANAGER, Role.OWNER}),
    Capability.REOPEN_CLOSED_BILL: frozenset({Role.MANAGER, Role.OWNER}),
    Capability.EDIT_MENU_AVAILABILITY: frozenset({Role.MANAGER, Role.OWNER}),
    Capability.EDIT_MENU_FULL: frozenset({Role.OWNER}),
    Capability.SET_PRICE_RULES: frozenset({Role.MANAGER, Role.OWNER}),
    Capability.MANAGE_WAITER_STAFF: frozenset({Role.MANAGER, Role.OWNER}),
    Capability.MANAGE_ALL_STAFF: frozenset({Role.OWNER}),
    Capability.GENERATE_TABLE_QRS: frozenset({Role.MANAGER, Role.OWNER}),
    Capability.DAY_CLOSE_AND_REPORTS: frozenset({Role.MANAGER, Role.OWNER}),
    Capability.EXPORT_INTEGRATIONS: frozenset({Role.OWNER}),
    Capability.MANAGE_SUBSCRIPTION_BILLING: frozenset({Role.OWNER}),
    Capability.VIEW_ANALYTICS: frozenset({Role.MANAGER, Role.OWNER}),
    Capability.EDIT_EXPECTED_PREP: frozenset({Role.MANAGER, Role.OWNER}),
}


@dataclass(frozen=True)
class StaffActor:
    """An authenticated staff user. `roles` holds every (outlet_id, role)
    pair the user holds — a user may hold different roles at different
    outlets (docs/SPEC.md §6)."""

    actor_type: Literal["staff"]
    user_id: UUID
    roles: frozenset[tuple[UUID, Role]]


@dataclass(frozen=True)
class CustomerActor:
    """An unauthenticated guest, identified by a live TabSession. The caller
    (an API dependency) must have already verified the session is
    unexpired and unrevoked before constructing this — this class only
    records which tab it is scoped to."""

    actor_type: Literal["customer"]
    tab_session_id: UUID
    tab_id: UUID


@dataclass(frozen=True)
class PlatformAdminActor:
    actor_type: Literal["platform_admin"]
    user_id: UUID


Actor = StaffActor | CustomerActor | PlatformAdminActor


class PermissionDeniedError(Exception):
    def __init__(self, *, capability: Capability | None, outlet_id: UUID | None) -> None:
        self.capability = capability
        self.outlet_id = outlet_id
        super().__init__(f"permission denied: capability={capability} outlet_id={outlet_id}")


def assert_can(actor: Actor, capability: Capability, outlet_id: UUID) -> None:
    """Outlet-scoped staff capability check. Raises PermissionDeniedError,
    which the API layer maps to HTTP 403, unless `actor` holds a role at
    `outlet_id` that the matrix grants `capability` to."""
    if not isinstance(actor, StaffActor):
        raise PermissionDeniedError(capability=capability, outlet_id=outlet_id)
    allowed_roles = CAPABILITY_MATRIX.get(capability, frozenset())
    roles_at_outlet = {role for (oid, role) in actor.roles if oid == outlet_id}
    if not (roles_at_outlet & allowed_roles):
        raise PermissionDeniedError(capability=capability, outlet_id=outlet_id)


def assert_can_write_own_tab(actor: Actor, tab_id: UUID) -> None:
    """Customer writes (place order, ack a line, request bill/waiter) never
    go through the staff role matrix — only through ownership of a live
    TabSession for that exact tab. See docs/DECISIONS.md "Customer actor
    model for unauthenticated guests"."""
    if not isinstance(actor, CustomerActor):
        raise PermissionDeniedError(capability=None, outlet_id=None)
    if actor.tab_id != tab_id:
        raise PermissionDeniedError(capability=None, outlet_id=None)


def assert_is_platform_admin(actor: Actor) -> None:
    if not isinstance(actor, PlatformAdminActor):
        raise PermissionDeniedError(capability=None, outlet_id=None)


def can(actor: Actor, capability: Capability, outlet_id: UUID) -> bool:
    """Non-raising form of `assert_can`, for shaping a response (never for gating a write)."""
    try:
        assert_can(actor, capability, outlet_id)
    except PermissionDeniedError:
        return False
    return True
