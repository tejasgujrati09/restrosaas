import pytest

from app.core.money import format_inr, round_bill_total


@pytest.mark.parametrize(
    ("paise", "expected"),
    [
        (0, "₹0.00"),
        (5, "₹0.05"),
        (100, "₹1.00"),
        (150, "₹1.50"),
        (99999, "₹999.99"),
        (100000, "₹1,000.00"),
        (12345600, "₹1,23,456.00"),
        (123456700, "₹12,34,567.00"),
        (-15000, "-₹150.00"),
    ],
)
def test_format_inr(paise: int, expected: str) -> None:
    assert format_inr(paise) == expected


def test_round_bill_total_rounds_down_below_half_rupee() -> None:
    rounded, round_off = round_bill_total(10049)
    assert rounded == 10000
    assert round_off == -49


def test_round_bill_total_rounds_up_at_or_above_half_rupee() -> None:
    rounded, round_off = round_bill_total(10050)
    assert rounded == 10100
    assert round_off == 50


def test_round_bill_total_exact_rupee_has_zero_round_off() -> None:
    rounded, round_off = round_bill_total(10000)
    assert rounded == 10000
    assert round_off == 0


def test_round_bill_total_rejects_negative() -> None:
    with pytest.raises(ValueError):
        round_bill_total(-1)
