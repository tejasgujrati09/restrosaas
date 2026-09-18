"""Price-rule evaluation (docs/DECISIONS.md "Price rules").

`effective_price` is pure: the caller supplies the outlet timezone, so the
same instant can be a happy-hour price in Mumbai and a regular price in UTC.
The result's price is what gets snapshotted onto an `OrderLine` together with
`price_rule_id`. The price is in the outlet's inclusive/exclusive tax mode,
exactly like `MenuItem.base_price_paise`; modifier deltas are never discounted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo


class RuleScope(StrEnum):
    ITEM = "item"
    CATEGORY = "category"
    ALL = "all"


class RuleType(StrEnum):
    FIXED = "fixed"
    PERCENT_OFF = "percent_off"


_SPECIFICITY = {RuleScope.ITEM: 3, RuleScope.CATEGORY: 2, RuleScope.ALL: 1}


@dataclass(frozen=True)
class PriceRuleSpec:
    id: UUID
    scope: RuleScope
    target_id: UUID | None
    rule_type: RuleType
    # fixed: paise. percent_off: percent * 100 (basis points).
    value: int
    # Python weekday numbers: 0 = Monday ... 6 = Sunday.
    days_of_week: frozenset[int]
    start_time: time
    end_time: time
    valid_from: datetime | None
    valid_to: datetime | None
    active: bool


@dataclass(frozen=True)
class PricedItem:
    item_id: UUID
    category_id: UUID
    base_price_paise: int


@dataclass(frozen=True)
class EffectivePrice:
    unit_price_paise: int
    price_rule_id: UUID | None


def _in_time_window(rule: PriceRuleSpec, local: datetime) -> bool:
    """Window check in outlet-local time. A window that crosses midnight
    (start > end) belongs to the weekday it starts on."""
    now_t = local.time()
    weekday = local.weekday()
    if rule.start_time == rule.end_time:
        return weekday in rule.days_of_week
    if rule.start_time < rule.end_time:
        return weekday in rule.days_of_week and rule.start_time <= now_t < rule.end_time
    if now_t >= rule.start_time:
        return weekday in rule.days_of_week
    if now_t < rule.end_time:
        return (weekday - 1) % 7 in rule.days_of_week
    return False


def _applies(rule: PriceRuleSpec, item: PricedItem, at: datetime, local: datetime) -> bool:
    if not rule.active:
        return False
    if rule.valid_from is not None and at < rule.valid_from:
        return False
    if rule.valid_to is not None and at >= rule.valid_to:
        return False
    if rule.scope == RuleScope.ITEM and rule.target_id != item.item_id:
        return False
    if rule.scope == RuleScope.CATEGORY and rule.target_id != item.category_id:
        return False
    return _in_time_window(rule, local)


def _rule_price(rule: PriceRuleSpec, base_price_paise: int) -> int:
    if rule.rule_type == RuleType.FIXED:
        return rule.value
    discount = (base_price_paise * rule.value + 5000) // 10_000
    return base_price_paise - discount


def effective_price(
    item: PricedItem, rules: Sequence[PriceRuleSpec], at: datetime, tz: ZoneInfo
) -> EffectivePrice:
    if at.tzinfo is None:
        raise ValueError("at must be timezone-aware")
    at_utc = at.astimezone(UTC)
    local = at_utc.astimezone(tz)
    candidates = [
        (r, _rule_price(r, item.base_price_paise))
        for r in rules
        if _applies(r, item, at_utc, local)
    ]
    if not candidates:
        return EffectivePrice(item.base_price_paise, None)
    rule, price = min(candidates, key=lambda c: (-_SPECIFICITY[c[0].scope], c[1], str(c[0].id)))
    return EffectivePrice(price, rule.id)


def next_boundary(rule: PriceRuleSpec, at: datetime, tz: ZoneInfo) -> datetime | None:
    """When the rule's daily window next ends, for the "happy hour until 8 PM"
    badge. None when the window is all-day."""
    if rule.start_time == rule.end_time:
        return None
    local = at.astimezone(tz)
    end = local.replace(
        hour=rule.end_time.hour,
        minute=rule.end_time.minute,
        second=0,
        microsecond=0,
    )
    if end <= local:
        end += timedelta(days=1)
    return end
