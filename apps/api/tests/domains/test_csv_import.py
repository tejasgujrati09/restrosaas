from __future__ import annotations

from app.domains.menu.csv_import import (
    ExistingItem,
    ImportContext,
    diff_menu,
    parse_menu_csv,
)

CTX = ImportContext(
    tax_classes={"food 5%": ("Food 5%", False), "liquor vat": ("Liquor VAT", True)},
    stations={"bar": "Bar"},
    modifier_groups={"spice": "Spice"},
    liquor_licensed=True,
)
HEADER = (
    "category,item,description,price,tax_class,veg,is_liquor,station,available,sku,modifier_groups"
)


def parse(*rows: str, ctx: ImportContext = CTX, header: str = HEADER):  # type: ignore[no-untyped-def]
    return parse_menu_csv("\n".join([header, *rows]), ctx)


def test_valid_row_becomes_paise_without_floats() -> None:
    result = parse("Starters,Paneer Tikka,Smoky,320.50,food 5%,yes,no,,y,SKU1,spice")
    assert result.errors == []
    row = result.rows[0]
    assert (row.price_paise, row.tax_class, row.veg, row.sku, row.modifier_groups) == (
        32050,
        "Food 5%",
        True,
        "SKU1",
        ("Spice",),
    )


def test_rupee_sign_commas_and_defaults() -> None:
    row = parse('Mains,Thali,,"₹1,250",Food 5%,,,,,,').rows[0]
    assert row.price_paise == 125000
    assert (row.veg, row.is_liquor, row.available, row.station, row.description) == (
        True,
        False,
        True,
        None,
        None,
    )


def test_liquor_row_needs_liquor_tax_class_and_license() -> None:
    ok = parse("Bar,Whisky,,450,Liquor VAT,no,yes,Bar,,,")
    assert ok.errors == [] and ok.rows[0].station == "Bar"
    mismatch = parse("Bar,Whisky,,450,Food 5%,no,yes,,,,")
    assert [e.column for e in mismatch.errors] == ["is_liquor"]
    unlicensed = ImportContext(
        CTX.tax_classes, CTX.stations, CTX.modifier_groups, liquor_licensed=False
    )
    assert (
        "licensed"
        in parse("Bar,Whisky,,450,Liquor VAT,no,yes,,,,", ctx=unlicensed).errors[0].message
    )


def test_every_bad_cell_is_reported_with_row_number() -> None:
    result = parse(
        ",,,abc,nope,maybe,,ghost,,,unknown",
        "Starters,Ok,,10,Food 5%,,,,,,",
    )
    assert {e.row for e in result.errors} == {2}
    assert {e.column for e in result.errors} == {
        "category",
        "item",
        "price",
        "tax_class",
        "veg",
        "station",
        "modifier_groups",
    }
    # The invalid row is never returned; the valid one still parses. The API refuses to
    # apply any file that has errors, so a partly-valid file cannot half-import.
    assert [r.item for r in result.rows] == ["Ok"]


def test_price_rejects_more_than_two_decimals_and_negatives() -> None:
    for bad in ("10.999", "-5", "", "1e3", "1.2.3"):
        assert parse(f"A,B,,{bad},Food 5%,,,,,,").errors[0].column == "price", bad


def test_header_problems_are_reported_once() -> None:
    result = parse_menu_csv("category,item,pric\nA,B,1", CTX)
    assert {(e.row, e.column) for e in result.errors} == {
        (1, "price"),
        (1, "tax_class"),
        (1, "pric"),
    }
    assert result.rows == []


def test_header_is_case_and_space_insensitive_and_blank_rows_are_skipped() -> None:
    text = " Category , ITEM,price,Tax_Class\nA,B,1,food 5%\n,,,\n"
    result = parse_menu_csv(text, CTX)
    assert result.errors == [] and len(result.rows) == 1


def test_duplicate_items_in_file_are_flagged() -> None:
    result = parse("A,Dish,,10,Food 5%,,,,,,", "a,dish,,12,Food 5%,,,,,,")
    assert result.errors[0].row == 3 and "Duplicate" in result.errors[0].message


def test_row_limit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("app.domains.menu.csv_import.MAX_ROWS", 2)
    result = parse("A,1,,1,Food 5%,,,,,,", "A,2,,1,Food 5%,,,,,,", "A,3,,1,Food 5%,,,,,,")
    assert "Too many rows" in result.errors[-1].message


def test_empty_file_reports_missing_columns() -> None:
    assert len(parse_menu_csv("", CTX).errors) == 4


def _existing(**over: object) -> ExistingItem:
    fields: dict[str, object] = {
        "category": "Starters",
        "item": "Paneer Tikka",
        "description": None,
        "price_paise": 32000,
        "tax_class": "Food 5%",
        "veg": True,
        "is_liquor": False,
        "station": None,
        "available": True,
        "sku": None,
        "modifier_groups": (),
    }
    fields.update(over)
    return ExistingItem(**fields)  # type: ignore[arg-type]


def test_diff_classifies_added_changed_unchanged_and_missing() -> None:
    rows = parse(
        "Starters,Paneer Tikka,,320,Food 5%,,,,,,",  # unchanged
        "Starters,Spring Roll,,150,Food 5%,,,,,,",  # added
        "Desserts,Kulfi,,90,Food 5%,,,,,,",  # added + new category
    ).rows
    diff = diff_menu(rows, [_existing(), _existing(item="Old Dish")], ["Starters"])
    assert diff.new_categories == ["Desserts"]
    assert [r.item for r in diff.added] == ["Spring Roll", "Kulfi"]
    assert diff.unchanged == 1 and diff.changed == []
    assert diff.not_in_file == [("Starters", "Old Dish")]


def test_diff_reports_field_level_changes_and_matches_names_case_insensitively() -> None:
    rows = parse("starters,paneer tikka,Now smoky,350,Food 5%,no,,,n,,spice").rows
    diff = diff_menu(rows, [_existing()], ["Starters"])
    (change,) = diff.changed
    assert (change.category, change.item) == ("Starters", "Paneer Tikka")
    assert change.changes == {
        "description": (None, "Now smoky"),
        "price_paise": (32000, 35000),
        "veg": (True, False),
        "available": (True, False),
        "modifier_groups": ((), ("Spice",)),
    }
    assert diff.new_categories == []


def test_digest_is_stable_and_changes_with_the_diff() -> None:
    rows = parse("A,X,,10,Food 5%,,,,,,").rows
    d1 = diff_menu(rows, [], [])
    d2 = diff_menu(rows, [], [])
    assert d1.digest() == d2.digest()
    other = diff_menu(parse("A,X,,11,Food 5%,,,,,,").rows, [], [])
    assert d1.digest() != other.digest()
