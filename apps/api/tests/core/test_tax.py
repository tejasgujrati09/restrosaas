import pytest

from app.core.tax import BillTaxTotals, LineTaxBreakdown, aggregate_bill_tax, compute_line_tax


def test_zero_rated_line_has_no_tax() -> None:
    result = compute_line_tax(
        unit_price_paise=10000, qty=2, rate_bp=0, is_liquor=False, prices_include_tax=True
    )
    assert result == LineTaxBreakdown(
        taxable_value_paise=20000,
        tax_amount_paise=0,
        cgst_paise=0,
        sgst_paise=0,
        liquor_vat_paise=0,
    )


def test_inclusive_food_line_splits_cgst_sgst_equally() -> None:
    # ₹105 inclusive at 5% GST -> ₹100 taxable + ₹2.50 CGST + ₹2.50 SGST.
    result = compute_line_tax(
        unit_price_paise=10500, qty=1, rate_bp=500, is_liquor=False, prices_include_tax=True
    )
    assert result == LineTaxBreakdown(
        taxable_value_paise=10000,
        tax_amount_paise=500,
        cgst_paise=250,
        sgst_paise=250,
        liquor_vat_paise=0,
    )


def test_exclusive_food_line_adds_tax_on_top() -> None:
    # ₹100 exclusive at 18% GST -> ₹18 tax, split ₹9/₹9.
    result = compute_line_tax(
        unit_price_paise=10000, qty=1, rate_bp=1800, is_liquor=False, prices_include_tax=False
    )
    assert result == LineTaxBreakdown(
        taxable_value_paise=10000,
        tax_amount_paise=1800,
        cgst_paise=900,
        sgst_paise=900,
        liquor_vat_paise=0,
    )


def test_liquor_line_gets_vat_not_gst() -> None:
    # ₹200 exclusive at 25% state VAT -> ₹50 VAT, no CGST/SGST.
    result = compute_line_tax(
        unit_price_paise=20000, qty=1, rate_bp=2500, is_liquor=True, prices_include_tax=False
    )
    assert result == LineTaxBreakdown(
        taxable_value_paise=20000,
        tax_amount_paise=5000,
        cgst_paise=0,
        sgst_paise=0,
        liquor_vat_paise=5000,
    )


def test_inclusive_price_rounds_taxable_value_half_up() -> None:
    # ₹100.01 inclusive at 5% GST does not divide evenly; taxable value
    # rounds half up rather than truncating or floating.
    result = compute_line_tax(
        unit_price_paise=10001, qty=1, rate_bp=500, is_liquor=False, prices_include_tax=True
    )
    assert result.taxable_value_paise == 9525
    assert result.tax_amount_paise == 476


def test_multiplies_by_quantity() -> None:
    result = compute_line_tax(
        unit_price_paise=10000, qty=3, rate_bp=0, is_liquor=False, prices_include_tax=False
    )
    assert result.taxable_value_paise == 30000


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        (
            {
                "unit_price_paise": 100,
                "qty": 0,
                "rate_bp": 0,
                "is_liquor": False,
                "prices_include_tax": True,
            },
            "qty",
        ),
        (
            {
                "unit_price_paise": -1,
                "qty": 1,
                "rate_bp": 0,
                "is_liquor": False,
                "prices_include_tax": True,
            },
            "unit_price_paise",
        ),
        (
            {
                "unit_price_paise": 100,
                "qty": 1,
                "rate_bp": -1,
                "is_liquor": False,
                "prices_include_tax": True,
            },
            "rate_bp",
        ),
    ],
)
def test_rejects_invalid_input(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        compute_line_tax(**kwargs)  # type: ignore[arg-type]


def test_aggregate_bill_tax_of_no_lines_is_zero() -> None:
    assert aggregate_bill_tax([]) == BillTaxTotals(0, 0, 0, 0, 0)


def test_aggregate_bill_tax_sums_food_and_liquor_lines() -> None:
    food = compute_line_tax(
        unit_price_paise=10500, qty=1, rate_bp=500, is_liquor=False, prices_include_tax=True
    )
    liquor = compute_line_tax(
        unit_price_paise=20000, qty=1, rate_bp=2500, is_liquor=True, prices_include_tax=False
    )
    totals = aggregate_bill_tax([food, liquor])
    assert totals == BillTaxTotals(
        taxable_value_paise=30000,
        cgst_paise=250,
        sgst_paise=250,
        liquor_vat_paise=5000,
        tax_amount_paise=5500,
    )
