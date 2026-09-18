"""Running total for a live tab. An estimate: the bill is computed once at
tab close (Milestone 5). Built on `compute_line_tax`, so per-line taxable
value and the CGST/SGST or VAT split match what the bill will use.

Service charge is a separate line on the taxable value with no GST on it;
whether GST applies to it is an open question for the CA
(docs/DECISIONS.md "Milestone 3 choices"). No rounding to whole rupees here:
`round_off` happens once, at bill issue.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.tax import aggregate_bill_tax, compute_line_tax


@dataclass(frozen=True)
class TotalsLine:
    unit_gross_paise: int
    qty: int
    rate_bp: int
    is_liquor: bool
    prices_include_tax: bool


@dataclass(frozen=True)
class TabTotals:
    items_paise: int
    taxable_value_paise: int
    cgst_paise: int
    sgst_paise: int
    liquor_vat_paise: int
    service_charge_paise: int
    estimated_total_paise: int


def compute_tab_totals(
    lines: Sequence[TotalsLine], *, service_charge_bp: int, service_charge_removed: bool
) -> TabTotals:
    breakdowns = [
        compute_line_tax(
            unit_price_paise=line.unit_gross_paise,
            qty=line.qty,
            rate_bp=line.rate_bp,
            is_liquor=line.is_liquor,
            prices_include_tax=line.prices_include_tax,
        )
        for line in lines
    ]
    tax = aggregate_bill_tax(breakdowns)
    service_charge = 0
    if not service_charge_removed:
        service_charge = (tax.taxable_value_paise * service_charge_bp + 5000) // 10_000
    return TabTotals(
        items_paise=sum(line.unit_gross_paise * line.qty for line in lines),
        taxable_value_paise=tax.taxable_value_paise,
        cgst_paise=tax.cgst_paise,
        sgst_paise=tax.sgst_paise,
        liquor_vat_paise=tax.liquor_vat_paise,
        service_charge_paise=service_charge,
        estimated_total_paise=tax.taxable_value_paise + tax.tax_amount_paise + service_charge,
    )
