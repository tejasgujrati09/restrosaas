"""Pure functions: page extractions -> editable draft rows -> the existing CSV format.

The CSV is written here, by us, with the same columns `csv_import.COLUMNS` defines, so the
existing parser is the single validator. Nothing in this module does I/O."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation

from app.domains.menu.csv_import import COLUMNS
from app.domains.menu.extract.schema import (
    Defaults,
    DraftRow,
    ExtractedItem,
    PageExtraction,
    PriceOption,
)

_PRICE = re.compile(r"^\d+(\.\d{1,2})?$")
_CURRENCY = re.compile(r"(₹|\brs\.?|\binr\b|/-)", re.IGNORECASE)
_FORMULA_LEAD = "=+-@\t\r"
_SPACES = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    """Collapse whitespace and drop leading characters a spreadsheet would run as a formula."""
    text = _SPACES.sub(" ", value or "").strip()
    return text.lstrip(_FORMULA_LEAD).strip()


def parse_price(raw: str | None) -> str | None:
    """Rupees as printed -> "120" or "120.50", or None when it is not one clean number."""
    if raw is None:
        return None
    text = _CURRENCY.sub("", raw).replace(",", "").strip()
    if not _PRICE.fullmatch(text):
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:  # pragma: no cover - the regex already guarantees a number
        return None
    return format(value.normalize(), "f") if value == value.to_integral() else format(value, "f")


def rows_from_pages(pages: Iterable[tuple[int, PageExtraction]]) -> list[DraftRow]:
    """Flatten pages (in page order) into rows, merging categories that continue across pages
    and skipping repeats. Category names keep the casing of their first appearance."""
    rows: list[DraftRow] = []
    canonical: dict[str, str] = {}
    current = ""
    for number, page in pages:
        if not page.is_menu:
            continue
        for category in page.categories:
            name = clean_text(category.name)
            carried = False
            if name:
                name = canonical.setdefault(name.lower(), name)
                current = name
            elif current:
                name, carried = current, True
            for item in category.items:
                rows.extend(_item_rows(item, name, number, carried))
    return _mark_duplicates(rows)


def _item_rows(item: ExtractedItem, category: str, page: int, carried: bool) -> list[DraftRow]:
    name = clean_text(item.name)
    if not name:
        return []
    options: list[PriceOption | None] = [*item.price_options] or [None]
    labelled = len(options) > 1
    result: list[DraftRow] = []
    for position, option in enumerate(options, start=1):
        notes: list[str] = []
        label = clean_text(option.label) if option is not None else ""
        if labelled and not label:
            label = f"Option {position}"
            notes.append("Several prices with no size names; rename this row.")
        price = parse_price(option.price) if option is not None else None
        if price is None:
            raw = clean_text(option.price) if option is not None else ""
            notes.append(f"Price unclear (read as '{raw}')." if raw else "No price found.")
        confidence = "low" if price is None else item.confidence
        if item.confidence == "low":
            notes.append("Low-confidence read; please check this row.")
        if carried:
            notes.append("No heading on this page; used the previous page's category.")
        if not category:
            notes.append("Category could not be determined.")
        if item.veg is None:
            notes.append("Veg or non-veg is not marked; check it.")
        if item.addons:
            notes.append(
                f"Add-ons seen ({'; '.join(clean_text(a) for a in item.addons)}). "
                "Add them as a modifier group after import."
            )
        result.append(
            DraftRow(
                category=category,
                item=f"{name} ({label})" if labelled else name,
                description=clean_text(item.description) or None,
                price=price or "",
                veg=item.veg,
                is_liquor=bool(item.is_liquor),
                confidence=confidence,
                source_page=page,
                notes=notes,
            )
        )
    return result


def _mark_duplicates(rows: list[DraftRow]) -> list[DraftRow]:
    first: dict[tuple[str, str], DraftRow] = {}
    for row in rows:
        key = (row.category.lower(), row.item.lower())
        earlier = first.get(key)
        if earlier is None:
            first[key] = row
            continue
        row.skip = True
        if earlier.price != row.price:
            row.notes.append("Appears again with a different price; kept the first one.")
            earlier.notes.append("Appears twice with different prices; check it.")
        else:
            row.notes.append("Duplicate of an earlier row; skipped.")
    return rows


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def build_csv(rows: Sequence[DraftRow], defaults: Defaults) -> tuple[str, list[int]]:
    """The CSV text and, for each CSV data row, the index of the draft row it came from (so a
    validator's "row 5" can be shown against the right draft row). Skipped rows are left out."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    included: list[int] = []
    for index, row in enumerate(rows):
        if row.skip:
            continue
        default_tax = defaults.liquor_tax_class if row.is_liquor else defaults.food_tax_class
        cells = {
            "category": clean_text(row.category),
            "item": clean_text(row.item),
            "description": clean_text(row.description),
            "price": row.price.strip(),
            "tax_class": row.tax_class or default_tax or "",
            "veg": "" if row.veg is None else _yes(row.veg),
            "is_liquor": _yes(row.is_liquor),
            "available": _yes(row.available),
        }
        writer.writerow([cells.get(column, "") for column in COLUMNS])
        included.append(index)
    return out.getvalue(), included
