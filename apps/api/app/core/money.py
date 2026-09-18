"""Money as integers in paise. No floats anywhere in this module.

Rounding happens exactly once, at bill issue, via `round_bill_total` — its
output paisa difference is what `Bill.round_off` stores.
"""

from __future__ import annotations


def format_inr(paise: int) -> str:
    """Render paise as Indian-grouped currency, e.g. 12345600 -> '₹1,23,456.00'."""
    sign = "-" if paise < 0 else ""
    whole_rupees, remainder_paise = divmod(abs(paise), 100)
    grouped = _group_indian(str(whole_rupees))
    return f"{sign}₹{grouped}.{remainder_paise:02d}"


def _group_indian(digits: str) -> str:
    if len(digits) <= 3:
        return digits
    last_three = digits[-3:]
    rest = digits[:-3]
    groups: list[str] = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    # `rest` is always non-empty here: len(digits) > 3 on entry, and the loop
    # above only ever leaves it at length 1 or 2, never 0.
    groups.insert(0, rest)
    return ",".join([*groups, last_three])


def round_bill_total(total_paise: int) -> tuple[int, int]:
    """Round a bill's grand total to the nearest rupee.

    Returns (rounded_total_paise, round_off_paise) where round_off_paise is
    the signed adjustment (rounded - original) to store on `Bill.round_off`.
    """
    if total_paise < 0:
        raise ValueError("total_paise must not be negative")
    rupees, remainder_paise = divmod(total_paise, 100)
    if remainder_paise >= 50:
        rupees += 1
    rounded_paise = rupees * 100
    round_off_paise = rounded_paise - total_paise
    return rounded_paise, round_off_paise
