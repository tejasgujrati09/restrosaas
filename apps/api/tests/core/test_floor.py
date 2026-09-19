import pytest

from app.core.floor import TableState, table_state


@pytest.mark.parametrize(
    ("tab", "rounds", "expected"),
    [
        (None, [], TableState.EMPTY),
        ("closed", ["served"], TableState.EMPTY),
        ("voided", [], TableState.EMPTY),
        ("open", [], TableState.SEATED),
        ("open", ["served", "cancelled"], TableState.SEATED),
        ("open", ["served", "placed"], TableState.ORDER_PENDING),
        ("open", ["accepted"], TableState.ORDER_PENDING),
        ("open", ["preparing"], TableState.ORDER_PENDING),
        ("open", ["ready"], TableState.ORDER_PENDING),
        ("bill_requested", ["served"], TableState.BILL_REQUESTED),
        ("bill_requested", ["placed"], TableState.BILL_REQUESTED),
    ],
)
def test_table_state(tab: str | None, rounds: list[str], expected: TableState) -> None:
    assert table_state(tab, rounds) is expected
