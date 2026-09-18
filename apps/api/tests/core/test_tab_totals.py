from __future__ import annotations

from app.core.tab_totals import TotalsLine, compute_tab_totals


def food(gross: int, qty: int = 1, *, inclusive: bool = True, rate_bp: int = 500) -> TotalsLine:
    return TotalsLine(gross, qty, rate_bp, False, inclusive)


def test_empty_tab_is_zero() -> None:
    totals = compute_tab_totals([], service_charge_bp=1000, service_charge_removed=False)
    assert totals.estimated_total_paise == 0
    assert totals.service_charge_paise == 0


def test_inclusive_prices_total_equals_menu_prices_plus_service_charge() -> None:
    # Two plates at ₹105 incl. 5% GST: taxable 200.00, tax 10.00 (5.00 + 5.00).
    totals = compute_tab_totals(
        [food(10500, 2)], service_charge_bp=1000, service_charge_removed=False
    )
    assert totals.items_paise == 21000
    assert totals.taxable_value_paise == 20000
    assert (totals.cgst_paise, totals.sgst_paise) == (500, 500)
    assert totals.service_charge_paise == 2000
    assert totals.estimated_total_paise == 21000 + 2000


def test_exclusive_prices_add_tax_on_top() -> None:
    totals = compute_tab_totals(
        [food(10000, 2, inclusive=False)], service_charge_bp=0, service_charge_removed=False
    )
    assert totals.items_paise == 20000
    assert totals.estimated_total_paise == 20000 + 1000


def test_liquor_is_vat_only_and_mixed_with_food() -> None:
    beer = TotalsLine(30000, 1, 2000, True, False)
    totals = compute_tab_totals(
        [food(10500), beer], service_charge_bp=0, service_charge_removed=False
    )
    assert totals.liquor_vat_paise == 6000
    assert (totals.cgst_paise, totals.sgst_paise) == (250, 250)
    assert totals.taxable_value_paise == 10000 + 30000


def test_removing_service_charge_drops_only_that_line() -> None:
    lines = [food(10500, 2)]
    kept = compute_tab_totals(lines, service_charge_bp=1000, service_charge_removed=False)
    removed = compute_tab_totals(lines, service_charge_bp=1000, service_charge_removed=True)
    assert removed.service_charge_paise == 0
    assert kept.estimated_total_paise - removed.estimated_total_paise == kept.service_charge_paise
    assert removed.taxable_value_paise == kept.taxable_value_paise


def test_service_charge_rounds_half_up_once() -> None:
    # 10% of 0.05 paise is not whole: taxable 5 paise * 1000bp = 0.5 -> rounds up to 1.
    totals = compute_tab_totals(
        [food(5, rate_bp=0)], service_charge_bp=1000, service_charge_removed=False
    )
    assert totals.service_charge_paise == 1
