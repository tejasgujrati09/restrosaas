"""Tax maths: CGST/SGST split for food, state VAT for liquor.

Rates are stored as basis points scaled by 100 (`rate_bp`), i.e. `rate_bp =
rate_percent * 100` — 5% is 500, 18% is 1800, 20.5% is 2050 — so a fractional
percentage rate never needs a float. `TaxClass.gst_rate` / `liquor_vat` on the
outlet map to `rate_bp` at the call site.

Whether `unit_price_paise` is tax-inclusive or tax-exclusive is an outlet
setting (`Outlet.prices_include_tax`), never assumed here — see
docs/DECISIONS.md "Tax storage: outlet-configurable inclusive/exclusive".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

_RATE_DENOMINATOR = 10_000  # rate_bp is percent * 100, so tax = value * rate_bp / 10_000


@dataclass(frozen=True)
class LineTaxBreakdown:
    taxable_value_paise: int
    tax_amount_paise: int
    cgst_paise: int
    sgst_paise: int
    liquor_vat_paise: int


@dataclass(frozen=True)
class BillTaxTotals:
    taxable_value_paise: int
    cgst_paise: int
    sgst_paise: int
    liquor_vat_paise: int
    tax_amount_paise: int


def _round_half_up(numerator: int, denominator: int) -> int:
    return (numerator + denominator // 2) // denominator


def compute_line_tax(
    *,
    unit_price_paise: int,
    qty: int,
    rate_bp: int,
    is_liquor: bool,
    prices_include_tax: bool,
) -> LineTaxBreakdown:
    """Derive one order line's taxable value and tax split from its snapshot.

    `unit_price_paise` is read exactly as the owner configured it — this
    function never adjusts it, only splits it into taxable value + tax so the
    displayed price matches the menu card to the paisa.
    """
    if qty <= 0:
        raise ValueError("qty must be positive")
    if unit_price_paise < 0:
        raise ValueError("unit_price_paise must not be negative")
    if rate_bp < 0:
        raise ValueError("rate_bp must not be negative")

    gross_paise = unit_price_paise * qty

    if rate_bp == 0:
        taxable_value_paise = gross_paise
        tax_amount_paise = 0
    elif prices_include_tax:
        taxable_value_paise = _round_half_up(
            gross_paise * _RATE_DENOMINATOR, _RATE_DENOMINATOR + rate_bp
        )
        tax_amount_paise = gross_paise - taxable_value_paise
    else:
        taxable_value_paise = gross_paise
        tax_amount_paise = _round_half_up(taxable_value_paise * rate_bp, _RATE_DENOMINATOR)

    if is_liquor:
        return LineTaxBreakdown(
            taxable_value_paise=taxable_value_paise,
            tax_amount_paise=tax_amount_paise,
            cgst_paise=0,
            sgst_paise=0,
            liquor_vat_paise=tax_amount_paise,
        )

    cgst_paise = tax_amount_paise // 2
    sgst_paise = tax_amount_paise - cgst_paise
    return LineTaxBreakdown(
        taxable_value_paise=taxable_value_paise,
        tax_amount_paise=tax_amount_paise,
        cgst_paise=cgst_paise,
        sgst_paise=sgst_paise,
        liquor_vat_paise=0,
    )


def aggregate_bill_tax(breakdowns: Sequence[LineTaxBreakdown]) -> BillTaxTotals:
    """Sum per-line breakdowns into bill-level totals.

    Summing line-level taxable values (rather than recomputing top-down from a
    bill subtotal) is what makes the invoice reconcile exactly — see
    docs/DECISIONS.md "Tax storage".
    """
    if not breakdowns:
        return BillTaxTotals(0, 0, 0, 0, 0)
    return BillTaxTotals(
        taxable_value_paise=sum(b.taxable_value_paise for b in breakdowns),
        cgst_paise=sum(b.cgst_paise for b in breakdowns),
        sgst_paise=sum(b.sgst_paise for b in breakdowns),
        liquor_vat_paise=sum(b.liquor_vat_paise for b in breakdowns),
        tax_amount_paise=sum(b.tax_amount_paise for b in breakdowns),
    )
