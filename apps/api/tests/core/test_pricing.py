from datetime import UTC, datetime, time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.core.pricing import (
    PricedItem,
    PriceRuleSpec,
    RuleScope,
    RuleType,
    effective_price,
    next_boundary,
)

IST = ZoneInfo("Asia/Kolkata")
ITEM = PricedItem(item_id=uuid4(), category_id=uuid4(), base_price_paise=40000)
ALL_DAYS = frozenset(range(7))


def rule(**overrides: object) -> PriceRuleSpec:
    fields: dict[str, object] = {
        "id": uuid4(),
        "scope": RuleScope.ALL,
        "target_id": None,
        "rule_type": RuleType.PERCENT_OFF,
        "value": 5000,
        "days_of_week": ALL_DAYS,
        "start_time": time(17, 0),
        "end_time": time(20, 0),
        "valid_from": None,
        "valid_to": None,
        "active": True,
    }
    fields.update(overrides)
    return PriceRuleSpec(**fields)  # type: ignore[arg-type]


def ist(day: int, hour: int, minute: int = 0) -> datetime:
    """September 2026: the 18th is a Friday."""
    return datetime(2026, 9, day, hour, minute, tzinfo=IST)


def price(rules: list[PriceRuleSpec], at: datetime, tz: ZoneInfo = IST) -> tuple[int, UUID | None]:
    result = effective_price(ITEM, rules, at, tz)
    return result.unit_price_paise, result.price_rule_id


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        effective_price(ITEM, [], datetime(2026, 9, 18, 18, 0), IST)


def test_no_rules_means_base_price() -> None:
    assert price([], ist(18, 18)) == (40000, None)


def test_window_start_inclusive_end_exclusive() -> None:
    happy = rule()
    assert price([happy], ist(18, 17, 0)) == (20000, happy.id)
    assert price([happy], ist(18, 19, 59)) == (20000, happy.id)
    assert price([happy], ist(18, 20, 0)) == (40000, None)
    assert price([happy], ist(18, 16, 59)) == (40000, None)


def test_weekday_filter() -> None:
    weekdays = rule(days_of_week=frozenset({0, 1, 2, 3, 4}))
    assert price([weekdays], ist(18, 18))[1] == weekdays.id  # Friday
    assert price([weekdays], ist(19, 18))[1] is None  # Saturday


def test_all_day_window_when_start_equals_end() -> None:
    all_day = rule(start_time=time(0, 0), end_time=time(0, 0), days_of_week=frozenset({4}))
    assert price([all_day], ist(18, 3))[1] == all_day.id
    assert price([all_day], ist(19, 3))[1] is None


def test_window_crossing_midnight_belongs_to_its_start_day() -> None:
    late = rule(start_time=time(22, 0), end_time=time(2, 0), days_of_week=frozenset({4}))
    assert price([late], ist(18, 23))[1] == late.id  # Fri 23:00
    assert price([late], ist(19, 1))[1] == late.id  # Sat 01:00, still Friday's window
    assert price([late], ist(19, 2))[1] is None  # end exclusive
    assert price([late], ist(19, 23))[1] is None  # Sat 23:00: Saturday is not a listed day
    assert price([late], ist(18, 1))[1] is None  # Fri 01:00: Thursday's window, not listed
    assert price([late], ist(18, 12))[1] is None  # between end and start


def test_sunday_night_window_wraps_into_monday() -> None:
    sunday = rule(start_time=time(23, 0), end_time=time(1, 0), days_of_week=frozenset({6}))
    assert price([sunday], ist(21, 0, 30))[1] == sunday.id  # Monday 00:30 IST


def test_evaluated_in_outlet_timezone_not_utc() -> None:
    late = rule(start_time=time(22, 0), end_time=time(2, 0), days_of_week=frozenset({4}))
    instant = datetime(2026, 9, 18, 20, 29, tzinfo=UTC)  # Sat 01:59 IST, Fri 20:29 UTC
    assert price([late], instant, IST)[1] == late.id
    assert price([late], instant, ZoneInfo("UTC"))[1] is None


def test_valid_from_and_valid_to_bound_the_rule() -> None:
    bounded = rule(valid_from=ist(18, 0), valid_to=ist(19, 0))
    assert price([bounded], ist(17, 18))[1] is None
    assert price([bounded], ist(18, 18))[1] == bounded.id
    assert price([bounded], ist(19, 18))[1] is None


def test_inactive_rule_is_ignored() -> None:
    assert price([rule(active=False)], ist(18, 18)) == (40000, None)


def test_item_and_category_scopes_only_match_their_target() -> None:
    item_rule = rule(scope=RuleScope.ITEM, target_id=ITEM.item_id)
    other_item = rule(scope=RuleScope.ITEM, target_id=uuid4())
    category_rule = rule(scope=RuleScope.CATEGORY, target_id=ITEM.category_id)
    other_category = rule(scope=RuleScope.CATEGORY, target_id=uuid4())
    at = ist(18, 18)
    assert price([item_rule], at)[1] == item_rule.id
    assert price([other_item], at)[1] is None
    assert price([category_rule], at)[1] == category_rule.id
    assert price([other_category], at)[1] is None


def test_fixed_rule_replaces_the_base_price() -> None:
    fixed = rule(rule_type=RuleType.FIXED, value=25000)
    assert price([fixed], ist(18, 18)) == (25000, fixed.id)


def test_percent_off_rounds_half_up_once() -> None:
    # 12.5% off Rs400.01: discount 5000.125 paise -> 5000; price 40001 - 5000.
    odd = PricedItem(ITEM.item_id, ITEM.category_id, 40001)
    quarter = rule(value=1250)
    assert effective_price(odd, [quarter], ist(18, 18), IST).unit_price_paise == 35001
    # 50% off 5 paise: 2.5 -> rounds up to 3, price 2.
    tiny = PricedItem(ITEM.item_id, ITEM.category_id, 5)
    assert effective_price(tiny, [rule()], ist(18, 18), IST).unit_price_paise == 2


def test_most_specific_scope_wins_even_when_a_broader_rule_is_cheaper() -> None:
    broad = rule(value=9000)  # 90% off everything
    item_rule = rule(
        scope=RuleScope.ITEM, target_id=ITEM.item_id, rule_type=RuleType.FIXED, value=30000
    )
    assert price([broad, item_rule], ist(18, 18)) == (30000, item_rule.id)


def test_category_beats_all() -> None:
    broad = rule(value=9000)
    category_rule = rule(scope=RuleScope.CATEGORY, target_id=ITEM.category_id, value=1000)
    assert price([broad, category_rule], ist(18, 18))[1] == category_rule.id


def test_same_scope_tie_picks_lowest_price_then_lowest_id() -> None:
    cheap = rule(value=6000)
    pricey = rule(value=2000)
    assert price([pricey, cheap], ist(18, 18))[1] == cheap.id
    a = rule(id=UUID(int=1))
    b = rule(id=UUID(int=2))
    assert price([b, a], ist(18, 18))[1] == a.id


def test_next_boundary() -> None:
    happy = rule()
    assert next_boundary(happy, ist(18, 18), IST) == ist(18, 20)
    assert next_boundary(happy, ist(18, 21), IST) == ist(19, 20)
    assert next_boundary(rule(start_time=time(0, 0), end_time=time(0, 0)), ist(18, 18), IST) is None
