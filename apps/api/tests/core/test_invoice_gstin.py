import pytest

from app.core.gstin import gstin_state_code, is_valid_gstin
from app.core.invoice import format_invoice_no, validate_invoice_prefix


def test_format_invoice_no() -> None:
    assert format_invoice_no("FY26", 1) == "FY26/1"
    assert format_invoice_no("ABCDEFGHIJ", 12345) == "ABCDEFGHIJ/12345"  # exactly 16


def test_format_invoice_no_rejects_over_16_characters() -> None:
    with pytest.raises(ValueError, match="16"):
        format_invoice_no("ABCDEFGHIJ", 123456)


@pytest.mark.parametrize("prefix", ["INV", "FY26-27", "A", "1234567890"])
def test_valid_prefixes(prefix: str) -> None:
    validate_invoice_prefix(prefix, 1)


@pytest.mark.parametrize("prefix", ["", "TOO-LONG-PREFIX", "IN/V", "IN V", "इन"])
def test_invalid_prefixes(prefix: str) -> None:
    with pytest.raises(ValueError):
        validate_invoice_prefix(prefix, 1)


def test_prefix_must_leave_room_for_the_current_counter() -> None:
    validate_invoice_prefix("ABCDEFGHIJ", 99999)
    with pytest.raises(ValueError, match="16"):
        validate_invoice_prefix("ABCDEFGHIJ", 100000)


def test_valid_gstin() -> None:
    assert is_valid_gstin("27AAPFU0939F1ZV")
    assert gstin_state_code("27AAPFU0939F1ZV") == "27"


@pytest.mark.parametrize(
    "gstin",
    ["27AAPFU0939F1ZX", "27AAPFU0939F1Z", "27aapfu0939f1zv", "", "27AAPFU0939F1AV"],
)
def test_invalid_gstin(gstin: str) -> None:
    assert not is_valid_gstin(gstin)
