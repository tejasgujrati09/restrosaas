"""Invoice number rendering. GST caps an invoice number at 16 characters
(docs/DECISIONS.md "Invoice numbering"). The counter (`outlet.next_invoice_no`)
never resets; a new series starts by changing the prefix.
"""

from __future__ import annotations

import re

MAX_INVOICE_NO_LENGTH = 16
_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,10}$")


def format_invoice_no(prefix: str, number: int) -> str:
    rendered = f"{prefix}/{number}"
    if len(rendered) > MAX_INVOICE_NO_LENGTH:
        raise ValueError(f"invoice number {rendered!r} exceeds {MAX_INVOICE_NO_LENGTH} characters")
    return rendered


def validate_invoice_prefix(prefix: str, next_number: int) -> None:
    """Letters, digits and hyphen only ('/' is the separator), and the next
    invoice number must still fit in 16 characters."""
    if not _PREFIX_PATTERN.fullmatch(prefix):
        raise ValueError("prefix must be 1-10 letters, digits or hyphens")
    format_invoice_no(prefix, next_number)
