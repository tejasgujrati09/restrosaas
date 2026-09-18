from app.core import flags


def test_defaults_are_sane() -> None:
    assert flags.DEFAULT_ACK_THRESHOLD_PAISE == 50_000
    assert flags.DEFAULT_WAITER_CONFIRM_MODE is False
    assert flags.DEFAULT_LIQUOR_APPROVAL_REQUIRED is False
    assert flags.DEFAULT_PRICES_INCLUDE_TAX is True
