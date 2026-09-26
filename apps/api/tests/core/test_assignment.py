from __future__ import annotations

from uuid import UUID

from app.core.assignment import Strategy, WaiterLoad, choose, least_loaded, nearest, rotation

A, B, C = (UUID(int=i) for i in (1, 2, 3))


def w(user: UUID, tables: int = 0, orders: int = 0, zone: int = 0) -> WaiterLoad:
    return WaiterLoad(user, tables, orders, zone)


def test_least_loaded_prefers_fewer_tables_then_fewer_orders_then_stable_id() -> None:
    assert least_loaded([w(A, 2), w(B, 1), w(C, 3)]) == B
    assert least_loaded([w(A, 1, 5), w(B, 1, 2)]) == B
    assert least_loaded([w(C, 1, 1), w(B, 1, 1)]) == B
    assert least_loaded([]) is None


def test_nearest_is_the_waiter_with_most_tables_in_the_zone() -> None:
    assert nearest([w(A, zone=1), w(B, zone=3), w(C, zone=0)]) == B


def test_nearest_breaks_ties_by_load_and_falls_back_when_nobody_serves_the_zone() -> None:
    assert nearest([w(A, 4, zone=2), w(B, 1, zone=2), w(C, 0, zone=0)]) == B
    assert nearest([w(A, 3), w(B, 1), w(C, 2)]) == B
    assert nearest([]) is None


def test_rotation_takes_turns_in_a_fixed_order_and_wraps() -> None:
    waiters = [w(C), w(A), w(B)]
    assert rotation(waiters, None) == A
    assert rotation(waiters, A) == B
    assert rotation(waiters, B) == C
    assert rotation(waiters, C) == A
    assert rotation([], A) is None


def test_rotation_skips_a_waiter_who_is_no_longer_eligible() -> None:
    assert rotation([w(A), w(C)], B) == C  # B left; the turn goes to the next one after B
    assert rotation([w(A), w(B)], UUID(int=99)) == A  # cursor past everyone wraps


def test_choose_dispatches_by_strategy() -> None:
    waiters = [w(A, 5, zone=0), w(B, 1, zone=1), w(C, 0, zone=0)]
    assert choose(Strategy.LEAST_LOADED, waiters, None) == C
    assert choose(Strategy.NEAREST, waiters, None) == B
    assert choose(Strategy.ROTATION, waiters, A) == B
