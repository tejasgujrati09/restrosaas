"""Rules behind the owner analytics screens: date ranges, comparison periods, buckets,
peak windows and CSV safety. Pure functions, no I/O (docs/DECISIONS.md "Owner analytics").

Every range is a pair of inclusive *local* dates in the outlet's timezone. The database is
queried with the matching half-open UTC interval from `utc_bounds`, so a day means the
outlet's day, not UTC's.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from statistics import median as _median
from zoneinfo import ZoneInfo

MAX_RANGE_DAYS = 366
# Fewer tickets than this and an average says little; the screen still shows it, flagged.
MIN_SAMPLES = 3
# An hour is "peak" when it is within this share of the busiest hour.
PEAK_SHARE = 0.75


class RangePreset(StrEnum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    THIS_WEEK = "this_week"
    THIS_MONTH = "this_month"
    PREVIOUS_MONTH = "previous_month"
    CUSTOM = "custom"


class Bucket(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class RangeError(ValueError):
    """The requested range cannot be used; the message is safe to show."""


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def resolve_range(
    preset: RangePreset,
    today: date,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> DateRange:
    """`today` is the outlet's local date. Weeks start on Monday."""
    if preset == RangePreset.TODAY:
        return DateRange(today, today)
    if preset == RangePreset.YESTERDAY:
        day = today - timedelta(days=1)
        return DateRange(day, day)
    if preset == RangePreset.LAST_7_DAYS:
        return DateRange(today - timedelta(days=6), today)
    if preset == RangePreset.LAST_30_DAYS:
        return DateRange(today - timedelta(days=29), today)
    if preset == RangePreset.THIS_WEEK:
        return DateRange(today - timedelta(days=today.weekday()), today)
    if preset == RangePreset.THIS_MONTH:
        return DateRange(today.replace(day=1), today)
    if preset == RangePreset.PREVIOUS_MONTH:
        last = today.replace(day=1) - timedelta(days=1)
        return DateRange(last.replace(day=1), last)
    if custom_start is None or custom_end is None:
        raise RangeError("Choose a start and an end date.")
    if custom_start > custom_end:
        raise RangeError("The start date must be on or before the end date.")
    if custom_end > today:
        raise RangeError("The end date cannot be in the future.")
    if (custom_end - custom_start).days + 1 > MAX_RANGE_DAYS:
        raise RangeError(f"Pick a range of at most {MAX_RANGE_DAYS} days.")
    return DateRange(custom_start, custom_end)


def previous_range(current: DateRange) -> DateRange:
    """The same number of days, ending the day before `current` starts."""
    end = current.start - timedelta(days=1)
    return DateRange(end - timedelta(days=current.days - 1), end)


def bucket_for(current: DateRange) -> Bucket:
    if current.days <= 31:
        return Bucket.DAY
    if current.days <= 180:
        return Bucket.WEEK
    return Bucket.MONTH


def bucket_start(day: date, bucket: Bucket) -> date:
    if bucket == Bucket.DAY:
        return day
    if bucket == Bucket.WEEK:
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def bucket_starts(current: DateRange, bucket: Bucket) -> list[date]:
    """Every bucket that overlaps the range, in order, so empty ones show as zero."""
    starts: list[date] = []
    day = bucket_start(current.start, bucket)
    while day <= current.end:
        starts.append(day)
        if bucket == Bucket.DAY:
            day += timedelta(days=1)
        elif bucket == Bucket.WEEK:
            day += timedelta(days=7)
        else:
            day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return starts


def utc_bounds(current: DateRange, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Half-open UTC interval `[start, end)` covering the local days in the range."""
    start = datetime.combine(current.start, time.min, tzinfo=tz)
    end = datetime.combine(current.end + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def change_pct(current: float | None, previous: float | None) -> float | None:
    """Percent change against the previous period, or None when there is nothing valid to
    compare with (no data, or a previous value of zero)."""
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def is_delayed(seconds: float, expected_minutes: int) -> bool:
    return seconds > expected_minutes * 60


def low_sample(count: int) -> bool:
    return count < MIN_SAMPLES


def peak_windows(per_hour: Sequence[int]) -> list[tuple[int, int]]:
    """Runs of consecutive hours whose count is within `PEAK_SHARE` of the busiest hour,
    as `(first_hour, hour_after_last)`. Empty when nothing happened."""
    top = max(per_hour, default=0)
    if top == 0:
        return []
    windows: list[tuple[int, int]] = []
    run_start: int | None = None
    for hour, count in enumerate(per_hour):
        busy = count >= top * PEAK_SHARE
        if busy and run_start is None:
            run_start = hour
        if not busy and run_start is not None:
            windows.append((run_start, hour))
            run_start = None
    if run_start is not None:
        windows.append((run_start, len(per_hour)))
    return windows


def median(values: Sequence[float]) -> float | None:
    return float(_median(values)) if values else None


class Quadrant(StrEnum):
    """Neutral labels: the owner decides what each means for their menu."""

    HIGH_VOLUME_HIGH_VALUE = "high_volume_high_value"
    HIGH_VOLUME_LOW_VALUE = "high_volume_low_value"
    LOW_VOLUME_HIGH_VALUE = "low_volume_high_value"
    LOW_VOLUME_LOW_VALUE = "low_volume_low_value"


def quadrant(units: int, value: int, median_units: float, median_value: float) -> Quadrant:
    """Where an item sits against the menu's median units and median order value."""
    high_volume = units >= median_units
    high_value = value >= median_value
    if high_volume:
        return Quadrant.HIGH_VOLUME_HIGH_VALUE if high_value else Quadrant.HIGH_VOLUME_LOW_VALUE
    return Quadrant.LOW_VOLUME_HIGH_VALUE if high_value else Quadrant.LOW_VOLUME_LOW_VALUE


def share_pct(part: int, whole: int) -> float | None:
    if whole <= 0:
        return None
    return round(part / whole * 100, 1)


def rounded_average(total: int, count: int) -> int | None:
    """Whole-paise average, half up. For display; nothing is booked from it."""
    if count <= 0:
        return None
    return (total * 2 + count) // (count * 2)


_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(cell: str) -> str:
    """Stops a spreadsheet from running an item or staff name as a formula."""
    return "'" + cell if cell.startswith(_FORMULA_LEADS) else cell
