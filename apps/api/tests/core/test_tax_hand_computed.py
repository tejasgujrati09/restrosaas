"""Ten hand-computed cases. Each expected value was worked out on paper from
the formulas in docs/DECISIONS.md, not by running the code under test."""

import pytest

from app.core.money import round_bill_total
from app.core.tax import aggregate_bill_tax, compute_line_tax

# (unit_price_paise, qty, rate_bp, is_liquor, prices_include_tax) ->
# (taxable, tax, cgst, sgst, liquor_vat)
CASES = [
    # 1. Rs105 incl. 5%: 105/1.05 = 100.00 exactly.
    ((10500, 1, 500, False, True), (10000, 500, 250, 250, 0)),
    # 2. Rs100 excl. 5%: tax 5.00.
    ((10000, 1, 500, False, False), (10000, 500, 250, 250, 0)),
    # 3. 2 x Rs120 incl. 18%: 24000/1.18 = 20338.98 -> 20339; tax 3661 splits 1830/1831.
    ((12000, 2, 1800, False, True), (20339, 3661, 1830, 1831, 0)),
    # 4. 3 x Rs99 excl. 5%: 29700 * 5% = 1485 splits 742/743 (odd paisa goes to SGST).
    ((9900, 3, 500, False, False), (29700, 1485, 742, 743, 0)),
    # 5. Rs250.50 excl. 18%: 25050 * 18% = 4509 splits 2254/2255.
    ((25050, 1, 1800, False, False), (25050, 4509, 2254, 2255, 0)),
    # 6. 2 x Rs450 liquor excl. 25% VAT: 90000 * 25% = 22500, no GST.
    ((45000, 2, 2500, True, False), (90000, 22500, 0, 0, 22500)),
    # 7. Rs350 liquor incl. 20% VAT: 35000/1.2 = 29166.67 -> 29167; VAT 5833.
    ((35000, 1, 2000, True, True), (29167, 5833, 0, 0, 5833)),
    # 8. 5 paise excl. 5%: 0.25 paise rounds down to 0.
    ((5, 1, 500, False, False), (5, 0, 0, 0, 0)),
    # 9. 10 paise excl. 5%: 0.5 paise rounds half up to 1; the paisa lands on SGST.
    ((10, 1, 500, False, False), (10, 1, 0, 1, 0)),
    # 10. Zero-rated: no tax at all.
    ((100, 1, 0, False, True), (100, 0, 0, 0, 0)),
]


@pytest.mark.parametrize(("args", "expected"), CASES)
def test_hand_computed_line(
    args: tuple[int, int, int, bool, bool], expected: tuple[int, int, int, int, int]
) -> None:
    price, qty, rate_bp, liquor, inclusive = args
    got = compute_line_tax(
        unit_price_paise=price,
        qty=qty,
        rate_bp=rate_bp,
        is_liquor=liquor,
        prices_include_tax=inclusive,
    )
    assert (
        got.taxable_value_paise,
        got.tax_amount_paise,
        got.cgst_paise,
        got.sgst_paise,
        got.liquor_vat_paise,
    ) == expected
    assert got.cgst_paise + got.sgst_paise + got.liquor_vat_paise == got.tax_amount_paise


def test_hand_computed_bill_reconciles_and_round_off_absorbs_final_paise() -> None:
    # Cases 4 and 9 on one bill: taxable 29700 + 10 = 29710; tax 1485 + 1 = 1486;
    # CGST 742, SGST 743 + 1 = 744. Total 29710 + 1486 = 31196 -> Rs312.00, round-off +4.
    lines = [
        compute_line_tax(
            unit_price_paise=9900, qty=3, rate_bp=500, is_liquor=False, prices_include_tax=False
        ),
        compute_line_tax(
            unit_price_paise=10, qty=1, rate_bp=500, is_liquor=False, prices_include_tax=False
        ),
    ]
    totals = aggregate_bill_tax(lines)
    assert (totals.taxable_value_paise, totals.cgst_paise, totals.sgst_paise) == (29710, 742, 744)
    assert totals.tax_amount_paise == 1486
    grand = totals.taxable_value_paise + totals.tax_amount_paise
    assert grand == 31196
    assert round_bill_total(grand) == (31200, 4)
