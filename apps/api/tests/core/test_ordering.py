from __future__ import annotations

from dataclasses import replace
from datetime import time
from uuid import uuid4

import pytest

from app.core.ordering import (
    CartError,
    CartLine,
    ModifierGroupSpec,
    ModifierSpec,
    OrderableItem,
    OutletOrderRules,
    build_line_snapshot,
    cart_item_ids,
    category_is_open,
    decide_staff_line_ack,
    item_is_orderable,
)
from app.core.pricing import EffectivePrice

NOON = time(12, 0)
RULES = OutletOrderRules(
    liquor_licensed=True, liquor_approval_required=False, prices_include_tax=True
)

SPICE = ModifierGroupSpec(
    id=uuid4(),
    name="Spice",
    min_select=1,
    max_select=1,
    modifiers=(
        ModifierSpec(uuid4(), "Mild", 0),
        ModifierSpec(uuid4(), "Hot", 1000),
    ),
)
ADDONS = ModifierGroupSpec(
    id=uuid4(),
    name="Add-ons",
    min_select=0,
    max_select=2,
    modifiers=(
        ModifierSpec(uuid4(), "Cheese", 2500),
        ModifierSpec(uuid4(), "Egg", 1500),
        ModifierSpec(uuid4(), "Mayo", 500),
    ),
)


def make_item(**overrides: object) -> OrderableItem:
    base = OrderableItem(
        id=uuid4(),
        name="Paneer Tikka",
        category_id=uuid4(),
        category_visible=True,
        category_from=None,
        category_to=None,
        available=True,
        is_liquor=False,
        needs_approval=False,
        base_price_paise=32000,
        tax_class_name="Food 5%",
        tax_rate_bp=500,
        groups=(SPICE, ADDONS),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def cart(item: OrderableItem, *modifiers: ModifierSpec, qty: int = 1) -> CartLine:
    return CartLine(item.id, qty, tuple(m.id for m in modifiers))


def snapshot(item: OrderableItem, line: CartLine, rules: OutletOrderRules = RULES):  # type: ignore[no-untyped-def]
    return build_line_snapshot(
        item, line, rules, EffectivePrice(item.base_price_paise, None), None, NOON
    )


def test_snapshot_freezes_price_tax_class_and_modifiers() -> None:
    item = make_item()
    hot, cheese = SPICE.modifiers[1], ADDONS.modifiers[0]
    snap = snapshot(item, cart(item, hot, cheese, qty=2))
    assert snap.item_name == "Paneer Tikka"
    assert snap.unit_price_paise == 32000
    assert snap.unit_gross_paise == 32000 + 1000 + 2500
    assert snap.line_total_paise == 2 * 35500
    assert snap.price_rule_id is None and snap.price_rule_name is None
    assert snap.tax_class == {
        "name": "Food 5%",
        "rate_bp": 500,
        "is_liquor": False,
        "prices_include_tax": True,
    }
    assert [m["name"] for m in snap.modifiers] == ["Hot", "Cheese"]
    assert snap.modifiers[0]["group_name"] == "Spice"


def test_price_rule_price_and_name_are_recorded() -> None:
    item = make_item(groups=())
    rule_id = uuid4()
    snap = build_line_snapshot(
        item,
        CartLine(item.id, 1, ()),
        RULES,
        EffectivePrice(20000, rule_id),
        "Happy hour",
        NOON,
    )
    assert (snap.unit_price_paise, snap.price_rule_id, snap.price_rule_name) == (
        20000,
        rule_id,
        "Happy hour",
    )


def test_rule_name_is_dropped_when_no_rule_applied() -> None:
    item = make_item(groups=())
    snap = build_line_snapshot(
        item, CartLine(item.id, 1, ()), RULES, EffectivePrice(32000, None), "stale name", NOON
    )
    assert snap.price_rule_name is None


def test_modifier_deltas_are_not_discounted_by_a_rule() -> None:
    item = make_item(groups=(ADDONS,))
    snap = build_line_snapshot(
        item,
        cart(item, ADDONS.modifiers[0]),
        RULES,
        EffectivePrice(16000, uuid4()),
        "Half price",
        NOON,
    )
    assert snap.unit_gross_paise == 16000 + 2500


def test_tax_mode_is_snapshotted() -> None:
    item = make_item(groups=())
    exclusive = replace(RULES, prices_include_tax=False)
    assert (
        snapshot(item, CartLine(item.id, 1, ()), exclusive).tax_class["prices_include_tax"] is False
    )


@pytest.mark.parametrize("qty", [0, -1, 51])
def test_quantity_out_of_range_is_rejected(qty: int) -> None:
    item = make_item(groups=())
    with pytest.raises(CartError) as exc:
        snapshot(item, CartLine(item.id, qty, ()))
    assert exc.value.code == "invalid_quantity"


@pytest.mark.parametrize(
    "overrides",
    [
        {"available": False},
        {"category_visible": False},
        {"category_from": time(6, 0), "category_to": time(11, 0)},
        {"is_liquor": True},
    ],
)
def test_unavailable_items_are_rejected(overrides: dict[str, object]) -> None:
    item = make_item(groups=(), **overrides)
    unlicensed = replace(RULES, liquor_licensed=False)
    with pytest.raises(CartError) as exc:
        snapshot(item, CartLine(item.id, 1, ()), unlicensed)
    assert exc.value.code == "item_unavailable"
    assert exc.value.details == {"item_id": str(item.id)}


def test_liquor_is_orderable_at_a_licensed_outlet() -> None:
    item = make_item(groups=(), is_liquor=True)
    assert snapshot(item, CartLine(item.id, 1, ())).tax_class["is_liquor"] is True


def test_item_needing_approval_is_blocked_only_when_the_outlet_requires_it() -> None:
    item = make_item(groups=(), needs_approval=True, is_liquor=True)
    line = CartLine(item.id, 1, ())
    assert snapshot(item, line).qty == 1
    with pytest.raises(CartError) as exc:
        snapshot(item, line, replace(RULES, liquor_approval_required=True))
    assert exc.value.code == "needs_waiter"


def test_required_group_must_be_chosen() -> None:
    item = make_item()
    with pytest.raises(CartError) as exc:
        snapshot(item, cart(item))
    assert exc.value.code == "invalid_modifiers"
    assert "Spice" in exc.value.message


def test_group_max_is_enforced() -> None:
    item = make_item()
    with pytest.raises(CartError) as exc:
        snapshot(item, cart(item, SPICE.modifiers[0], *ADDONS.modifiers))
    assert exc.value.code == "invalid_modifiers"
    assert "0 to 2" in exc.value.message


def test_exact_range_wording() -> None:
    item = make_item(groups=(SPICE,))
    with pytest.raises(CartError) as exc:
        snapshot(item, cart(item, *SPICE.modifiers))
    assert "Choose 1 for Spice" in exc.value.message


def test_modifier_from_another_item_is_rejected() -> None:
    item = make_item(groups=(SPICE,))
    foreign = ModifierSpec(uuid4(), "Foreign", 0)
    with pytest.raises(CartError) as exc:
        snapshot(item, cart(item, SPICE.modifiers[0], foreign))
    assert exc.value.details == {"modifier_id": str(foreign.id)}


def test_duplicate_modifier_is_rejected() -> None:
    item = make_item()
    mild = SPICE.modifiers[0]
    with pytest.raises(CartError):
        snapshot(item, cart(item, mild, mild))


@pytest.mark.parametrize(
    ("window", "now", "expected"),
    [
        ((None, None), time(3, 0), True),
        ((time(6, 0), time(6, 0)), time(3, 0), True),
        ((time(6, 0), time(11, 0)), time(6, 0), True),
        ((time(6, 0), time(11, 0)), time(11, 0), False),
        ((time(6, 0), time(11, 0)), time(5, 59), False),
        ((time(22, 0), time(2, 0)), time(23, 0), True),
        ((time(22, 0), time(2, 0)), time(1, 0), True),
        ((time(22, 0), time(2, 0)), time(12, 0), False),
    ],
)
def test_category_window(
    window: tuple[time | None, time | None], now: time, expected: bool
) -> None:
    assert category_is_open(window[0], window[1], now) is expected


def test_item_is_orderable_reflects_all_three_conditions() -> None:
    assert item_is_orderable(make_item(), NOON) is True
    assert item_is_orderable(make_item(available=False), NOON) is False


def test_cart_item_ids_collapses_repeats() -> None:
    a, b = uuid4(), uuid4()
    lines = [CartLine(a, 1, ()), CartLine(b, 1, ()), CartLine(a, 2, ())]
    assert cart_item_ids(lines) == {a, b}


@pytest.mark.parametrize(
    ("total", "live", "needs", "waived"),
    [
        (49_999, True, False, False),
        (50_000, True, True, False),
        (52_000, True, True, False),
        (52_000, False, False, True),
        (100, False, False, True),
    ],
)
def test_staff_line_ack_rule(total: int, live: bool, needs: bool, waived: bool) -> None:
    decision = decide_staff_line_ack(
        line_total_paise=total, threshold_paise=50_000, has_live_session=live
    )
    assert (decision.needs_customer_ack, decision.ack_waived) == (needs, waived)
