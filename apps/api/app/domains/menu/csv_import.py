"""Menu CSV import: parse, validate and diff. Pure functions, no I/O.

Prices in the file are rupees exactly as the owner would print them on the
menu card (docs/DECISIONS.md "Tax storage"); they become integer paise with
Decimal, never float. Nothing here writes to the database: the API previews the
diff first and applies it only when the owner confirms the same diff.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

COLUMNS = [
    "category",
    "item",
    "description",
    "price",
    "tax_class",
    "veg",
    "is_liquor",
    "station",
    "available",
    "sku",
    "modifier_groups",
]
REQUIRED = ("category", "item", "price", "tax_class")
MAX_ROWS = 2000
_TRUE = {"y", "yes", "true", "1"}
_FALSE = {"n", "no", "false", "0"}
_PRICE = re.compile(r"^\d+(\.\d{1,2})?$")


@dataclass(frozen=True)
class ImportContext:
    """What the file may reference. Keys are lower-cased names."""

    tax_classes: dict[str, tuple[str, bool]]  # lower name -> (canonical name, is liquor VAT)
    stations: dict[str, str]  # lower name -> canonical name
    modifier_groups: dict[str, str]
    liquor_licensed: bool


@dataclass(frozen=True)
class ParsedRow:
    category: str
    item: str
    description: str | None
    price_paise: int
    tax_class: str
    veg: bool
    is_liquor: bool
    station: str | None
    available: bool
    sku: str | None
    modifier_groups: tuple[str, ...]


@dataclass(frozen=True)
class RowError:
    row: int
    column: str | None
    message: str


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


def parse_menu_csv(text: str, ctx: ImportContext) -> ParseResult:
    result = ParseResult()
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    reader.fieldnames = header
    problems = [RowError(1, c, f"Missing column '{c}'.") for c in REQUIRED if c not in header] + [
        RowError(1, c, f"Unknown column '{c}'.") for c in header if c not in COLUMNS
    ]
    if problems:
        result.errors.extend(problems)
        return result

    seen: set[tuple[str, str]] = set()
    for number, raw in enumerate(reader, start=2):
        if number - 1 > MAX_ROWS:
            result.errors.append(RowError(number, None, f"Too many rows (limit {MAX_ROWS})."))
            break
        cells = {k: (v or "").strip() for k, v in raw.items() if k is not None}
        if not any(cells.values()):
            continue
        errors: list[RowError] = []
        row = _parse_row(number, cells, ctx, errors)
        if row is not None and not errors:
            key = (row.category.lower(), row.item.lower())
            if key in seen:
                errors.append(RowError(number, "item", "Duplicate item in this category."))
            seen.add(key)
        if errors:
            result.errors.extend(errors)
        elif row is not None:
            result.rows.append(row)
    return result


def _bool(value: str, default: bool) -> bool | None:
    lowered = value.lower()
    if not lowered:
        return default
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    return None


def _parse_row(
    number: int, cells: dict[str, str], ctx: ImportContext, errors: list[RowError]
) -> ParsedRow | None:
    def fail(column: str, message: str) -> None:
        errors.append(RowError(number, column, message))

    category, item = cells.get("category", ""), cells.get("item", "")
    if not category or len(category) > 100:
        fail("category", "Category is required (100 characters at most).")
    if not item or len(item) > 200:
        fail("item", "Item is required (200 characters at most).")

    price_text = cells.get("price", "").replace("₹", "").replace(",", "").strip()
    price_paise = 0
    if not _PRICE.fullmatch(price_text):
        fail(
            "price", "Price must be a number in rupees with at most 2 decimals, e.g. 120 or 120.50."
        )
    else:
        price_paise = int(Decimal(price_text) * 100)

    tax_entry = ctx.tax_classes.get(cells.get("tax_class", "").lower())
    if tax_entry is None:
        fail("tax_class", f"Unknown tax class '{cells.get('tax_class', '')}'. Create it first.")

    veg = _bool(cells.get("veg", ""), True)
    is_liquor = _bool(cells.get("is_liquor", ""), False)
    available = _bool(cells.get("available", ""), True)
    for column, value in (("veg", veg), ("is_liquor", is_liquor), ("available", available)):
        if value is None:
            fail(column, "Use yes or no.")

    station_name = cells.get("station", "")
    station = None
    if station_name:
        station = ctx.stations.get(station_name.lower())
        if station is None:
            fail("station", f"Unknown station '{station_name}'.")

    groups: list[str] = []
    for name in (g.strip() for g in cells.get("modifier_groups", "").split(";")):
        if not name:
            continue
        canonical = ctx.modifier_groups.get(name.lower())
        if canonical is None:
            fail("modifier_groups", f"Unknown modifier group '{name}'. Create it first.")
        else:
            groups.append(canonical)

    if tax_entry is not None and is_liquor is not None:
        if is_liquor != tax_entry[1]:
            fail("is_liquor", "Liquor items need a liquor VAT tax class, and food items a GST one.")
        elif is_liquor and not ctx.liquor_licensed:
            fail("is_liquor", "This outlet is not marked as liquor licensed.")

    if errors or tax_entry is None or veg is None or is_liquor is None or available is None:
        return None
    return ParsedRow(
        category=category,
        item=item,
        description=cells.get("description") or None,
        price_paise=price_paise,
        tax_class=tax_entry[0],
        veg=veg,
        is_liquor=is_liquor,
        station=station,
        available=available,
        sku=cells.get("sku") or None,
        modifier_groups=tuple(sorted(groups)),
    )


@dataclass(frozen=True)
class ExistingItem:
    category: str
    item: str
    description: str | None
    price_paise: int
    tax_class: str
    veg: bool
    is_liquor: bool
    station: str | None
    available: bool
    sku: str | None
    modifier_groups: tuple[str, ...]


_FIELDS = (
    "description",
    "price_paise",
    "tax_class",
    "veg",
    "is_liquor",
    "station",
    "available",
    "sku",
    "modifier_groups",
)


@dataclass(frozen=True)
class ItemChange:
    category: str
    item: str
    changes: dict[str, tuple[Any, Any]]


@dataclass(frozen=True)
class MenuDiff:
    new_categories: list[str]
    added: list[ParsedRow]
    changed: list[ItemChange]
    unchanged: int
    not_in_file: list[tuple[str, str]]

    def digest(self) -> str:
        """Stable fingerprint of what applying this diff would do, so the apply
        call can prove it is applying the diff the owner saw."""
        payload = {
            "new_categories": self.new_categories,
            "added": [asdict(r) for r in self.added],
            "changed": [asdict(c) for c in self.changed],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def diff_menu(
    rows: Iterable[ParsedRow], existing: Iterable[ExistingItem], existing_categories: Iterable[str]
) -> MenuDiff:
    by_key = {(e.category.lower(), e.item.lower()): e for e in existing}
    known_categories = {c.lower() for c in existing_categories}
    seen_keys: set[tuple[str, str]] = set()
    new_categories: list[str] = []
    added: list[ParsedRow] = []
    changed: list[ItemChange] = []
    unchanged = 0
    for row in rows:
        key = (row.category.lower(), row.item.lower())
        seen_keys.add(key)
        if row.category.lower() not in known_categories:
            known_categories.add(row.category.lower())
            new_categories.append(row.category)
        current = by_key.get(key)
        if current is None:
            added.append(row)
            continue
        diffs = {
            name: (getattr(current, name), getattr(row, name))
            for name in _FIELDS
            if getattr(current, name) != getattr(row, name)
        }
        if diffs:
            changed.append(ItemChange(current.category, current.item, diffs))
        else:
            unchanged += 1
    not_in_file = sorted((e.category, e.item) for k, e in by_key.items() if k not in seen_keys)
    return MenuDiff(new_categories, added, changed, unchanged, not_in_file)
