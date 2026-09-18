"""Turning a guest's cart into order-line snapshots (docs/SPEC.md §5 "Price
integrity"). Pure: the caller loads menu rows and price rules, this decides
whether the cart is valid and what to freeze onto each `OrderLine`.

The snapshot is everything a bill needs later. Editing or deleting a
`MenuItem`, modifier, tax class or price rule afterwards never changes it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time
from typing import Any
from uuid import UUID

from app.core.pricing import EffectivePrice

MAX_QTY = 50


class CartError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


@dataclass(frozen=True)
class ModifierSpec:
    id: UUID
    name: str
    price_delta_paise: int


@dataclass(frozen=True)
class ModifierGroupSpec:
    id: UUID
    name: str
    min_select: int
    max_select: int
    modifiers: tuple[ModifierSpec, ...]


@dataclass(frozen=True)
class OrderableItem:
    id: UUID
    name: str
    category_id: UUID
    category_visible: bool
    category_from: time | None
    category_to: time | None
    available: bool
    is_liquor: bool
    needs_approval: bool
    base_price_paise: int
    tax_class_name: str
    tax_rate_bp: int
    groups: tuple[ModifierGroupSpec, ...]


@dataclass(frozen=True)
class OutletOrderRules:
    liquor_licensed: bool
    liquor_approval_required: bool
    prices_include_tax: bool


@dataclass(frozen=True)
class CartLine:
    menu_item_id: UUID
    qty: int
    modifier_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class LineSnapshot:
    menu_item_id: UUID
    item_name: str
    qty: int
    unit_price_paise: int
    price_rule_id: UUID | None
    price_rule_name: str | None
    tax_class: dict[str, Any]
    modifiers: tuple[dict[str, Any], ...]
    unit_gross_paise: int
    line_total_paise: int


@dataclass(frozen=True)
class AckDecision:
    needs_customer_ack: bool
    ack_waived: bool


def category_is_open(
    available_from: time | None, available_to: time | None, local_now: time
) -> bool:
    """A category with no window is always open. A window that crosses
    midnight (from > to) is open late at night and early morning."""
    if available_from is None or available_to is None or available_from == available_to:
        return True
    if available_from < available_to:
        return available_from <= local_now < available_to
    return local_now >= available_from or local_now < available_to


def item_is_orderable(item: OrderableItem, local_now: time) -> bool:
    return (
        item.available
        and item.category_visible
        and category_is_open(item.category_from, item.category_to, local_now)
    )


def _selected_modifiers(
    item: OrderableItem, cart: CartLine
) -> list[tuple[ModifierGroupSpec, ModifierSpec]]:
    if len(set(cart.modifier_ids)) != len(cart.modifier_ids):
        raise CartError("invalid_modifiers", "Each option can only be chosen once.")
    by_id = {m.id: (g, m) for g in item.groups for m in g.modifiers}
    chosen: list[tuple[ModifierGroupSpec, ModifierSpec]] = []
    for modifier_id in cart.modifier_ids:
        if modifier_id not in by_id:
            raise CartError(
                "invalid_modifiers",
                f"That option is not available for {item.name}.",
                {"modifier_id": str(modifier_id)},
            )
        chosen.append(by_id[modifier_id])
    for group in item.groups:
        count = sum(1 for g, _ in chosen if g.id == group.id)
        if count < group.min_select or count > group.max_select:
            raise CartError(
                "invalid_modifiers",
                f"Choose {_range_text(group.min_select, group.max_select)} for {group.name}.",
                {"group_id": str(group.id)},
            )
    return chosen


def _range_text(low: int, high: int) -> str:
    if low == high:
        return str(low)
    return f"{low} to {high}"


def build_line_snapshot(
    item: OrderableItem,
    cart: CartLine,
    rules: OutletOrderRules,
    effective: EffectivePrice,
    price_rule_name: str | None,
    local_now: time,
) -> LineSnapshot:
    if cart.qty < 1 or cart.qty > MAX_QTY:
        raise CartError("invalid_quantity", f"Choose between 1 and {MAX_QTY}.")
    if not item_is_orderable(item, local_now):
        raise CartError(
            "item_unavailable",
            f"{item.name} is not available right now.",
            {"item_id": str(item.id)},
        )
    if item.is_liquor and not rules.liquor_licensed:
        raise CartError(
            "item_unavailable",
            f"{item.name} is not available right now.",
            {"item_id": str(item.id)},
        )
    if item.needs_approval and rules.liquor_approval_required:
        raise CartError(
            "needs_waiter",
            f"Please ask your waiter to add {item.name}.",
            {"item_id": str(item.id)},
        )
    chosen = _selected_modifiers(item, cart)
    modifiers = tuple(
        {
            "id": str(m.id),
            "name": m.name,
            "group_id": str(g.id),
            "group_name": g.name,
            "price_delta_paise": m.price_delta_paise,
        }
        for g, m in chosen
    )
    unit_gross = effective.unit_price_paise + sum(m.price_delta_paise for _, m in chosen)
    return LineSnapshot(
        menu_item_id=item.id,
        item_name=item.name,
        qty=cart.qty,
        unit_price_paise=effective.unit_price_paise,
        price_rule_id=effective.price_rule_id,
        price_rule_name=price_rule_name if effective.price_rule_id is not None else None,
        tax_class={
            "name": item.tax_class_name,
            "rate_bp": item.tax_rate_bp,
            "is_liquor": item.is_liquor,
            "prices_include_tax": rules.prices_include_tax,
        },
        modifiers=modifiers,
        unit_gross_paise=unit_gross,
        line_total_paise=unit_gross * cart.qty,
    )


def decide_staff_line_ack(
    *, line_total_paise: int, threshold_paise: int, has_live_session: bool
) -> AckDecision:
    """Staff-added lines at or above the outlet threshold need the guest's
    tap. On a tab with no live TabSession (a walk-in a waiter opened) there is
    no device to ask, so the requirement is waived and logged as `ack_waived`
    rather than silently dropped (docs/DECISIONS.md "Staff-added lines on a tab
    with no live TabSession")."""
    if not has_live_session:
        return AckDecision(needs_customer_ack=False, ack_waived=True)
    return AckDecision(needs_customer_ack=line_total_paise >= threshold_paise, ack_waived=False)


def cart_item_ids(lines: Sequence[CartLine]) -> set[UUID]:
    return {line.menu_item_id for line in lines}
