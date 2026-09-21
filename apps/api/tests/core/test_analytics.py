from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core import analytics as a

IST = ZoneInfo("Asia/Kolkata")
FRI = date(2026, 9, 18)  # a Friday


@pytest.mark.parametrize(
    ("preset", "start", "end"),
    [
        (a.RangePreset.TODAY, date(2026, 9, 18), date(2026, 9, 18)),
        (a.RangePreset.YESTERDAY, date(2026, 9, 17), date(2026, 9, 17)),
        (a.RangePreset.LAST_7_DAYS, date(2026, 9, 12), date(2026, 9, 18)),
        (a.RangePreset.LAST_30_DAYS, date(2026, 8, 20), date(2026, 9, 18)),
        (a.RangePreset.THIS_WEEK, date(2026, 9, 14), date(2026, 9, 18)),  # Monday start
        (a.RangePreset.THIS_MONTH, date(2026, 9, 1), date(2026, 9, 18)),
        (a.RangePreset.PREVIOUS_MONTH, date(2026, 8, 1), date(2026, 8, 31)),
    ],
)
def test_presets(preset: a.RangePreset, start: date, end: date) -> None:
    assert a.resolve_range(preset, FRI) == a.DateRange(start, end)


def test_previous_month_across_a_year_and_february() -> None:
    assert a.resolve_range(a.RangePreset.PREVIOUS_MONTH, date(2026, 1, 5)) == a.DateRange(
        date(2025, 12, 1), date(2025, 12, 31)
    )
    assert a.resolve_range(a.RangePreset.PREVIOUS_MONTH, date(2028, 3, 1)) == a.DateRange(
        date(2028, 2, 1), date(2028, 2, 29)
    )


def test_custom_range() -> None:
    got = a.resolve_range(a.RangePreset.CUSTOM, FRI, date(2026, 9, 1), date(2026, 9, 10))
    assert got == a.DateRange(date(2026, 9, 1), date(2026, 9, 10))
    assert got.days == 10


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (None, None, "Choose a start"),
        (date(2026, 9, 1), None, "Choose a start"),
        (date(2026, 9, 10), date(2026, 9, 1), "on or before"),
        (date(2026, 9, 1), date(2026, 9, 19), "future"),
        (date(2025, 9, 1), date(2026, 9, 18), "at most 366"),
    ],
)
def test_custom_range_rejects(start: date | None, end: date | None, message: str) -> None:
    with pytest.raises(a.RangeError, match=message):
        a.resolve_range(a.RangePreset.CUSTOM, FRI, start, end)


def test_custom_range_of_exactly_the_maximum_is_allowed() -> None:
    got = a.resolve_range(a.RangePreset.CUSTOM, FRI, date(2025, 9, 18), FRI)
    assert got.days == 366


def test_previous_range_is_the_same_length_just_before() -> None:
    assert a.previous_range(a.DateRange(date(2026, 9, 12), date(2026, 9, 18))) == a.DateRange(
        date(2026, 9, 5), date(2026, 9, 11)
    )
    one = a.DateRange(FRI, FRI)
    assert a.previous_range(one) == a.DateRange(date(2026, 9, 17), date(2026, 9, 17))


@pytest.mark.parametrize(
    ("days", "bucket"),
    [
        (1, a.Bucket.DAY),
        (31, a.Bucket.DAY),
        (32, a.Bucket.WEEK),
        (180, a.Bucket.WEEK),
        (181, a.Bucket.MONTH),
    ],
)
def test_bucket_for(days: int, bucket: a.Bucket) -> None:
    r = a.DateRange(date(2026, 1, 1), date.fromordinal(date(2026, 1, 1).toordinal() + days - 1))
    assert a.bucket_for(r) == bucket


def test_bucket_start() -> None:
    assert a.bucket_start(FRI, a.Bucket.DAY) == FRI
    assert a.bucket_start(FRI, a.Bucket.WEEK) == date(2026, 9, 14)
    assert a.bucket_start(FRI, a.Bucket.MONTH) == date(2026, 9, 1)


def test_bucket_starts_fill_empty_buckets() -> None:
    r = a.DateRange(date(2026, 9, 16), date(2026, 9, 18))
    assert a.bucket_starts(r, a.Bucket.DAY) == [date(2026, 9, 16), date(2026, 9, 17), FRI]
    r = a.DateRange(date(2026, 9, 10), date(2026, 9, 24))
    assert a.bucket_starts(r, a.Bucket.WEEK) == [
        date(2026, 9, 7),
        date(2026, 9, 14),
        date(2026, 9, 21),
    ]
    r = a.DateRange(date(2025, 11, 20), date(2026, 2, 3))
    assert a.bucket_starts(r, a.Bucket.MONTH) == [
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]


def test_utc_bounds_use_the_outlet_day_not_utc() -> None:
    lo, hi = a.utc_bounds(a.DateRange(FRI, FRI), IST)
    assert lo == datetime(2026, 9, 17, 18, 30, tzinfo=UTC)
    assert hi == datetime(2026, 9, 18, 18, 30, tzinfo=UTC)


def test_utc_bounds_on_a_dst_day_is_23_hours() -> None:
    ny = ZoneInfo("America/New_York")
    lo, hi = a.utc_bounds(a.DateRange(date(2026, 3, 8), date(2026, 3, 8)), ny)
    assert (hi - lo).total_seconds() == 23 * 3600


def test_change_pct() -> None:
    assert a.change_pct(108.4, 100) == 8.4
    assert a.change_pct(90, 100) == -10.0
    assert a.change_pct(5, 0) is None  # nothing valid to compare with
    assert a.change_pct(5, None) is None
    assert a.change_pct(None, 5) is None
    assert a.change_pct(0, 5) == -100.0


def test_delay_is_strictly_longer_than_expected() -> None:
    assert not a.is_delayed(600, 10)
    assert a.is_delayed(601, 10)


def test_low_sample() -> None:
    assert a.low_sample(2)
    assert not a.low_sample(3)


def test_peak_windows() -> None:
    assert a.peak_windows([0] * 24) == []
    assert a.peak_windows([]) == []
    hours = [0] * 24
    hours[12], hours[13], hours[14] = 20, 27, 14  # peak is 42; 75% of it is 31.5
    hours[19], hours[20], hours[21] = 31, 42, 39
    assert a.peak_windows(hours) == [(20, 22)]
    hours[8], hours[9], hours[10] = 40, 38, 5
    assert a.peak_windows(hours) == [(8, 10), (20, 22)]
    hours = [0] * 24
    hours[22], hours[23] = 10, 10  # a run that reaches midnight
    assert a.peak_windows(hours) == [(22, 24)]


def test_median() -> None:
    assert a.median([]) is None
    assert a.median([1, 5, 3]) == 3.0
    assert a.median([1, 2, 3, 4]) == 2.5


@pytest.mark.parametrize(
    ("units", "value", "expected"),
    [
        (10, 1000, a.Quadrant.HIGH_VOLUME_HIGH_VALUE),
        (10, 100, a.Quadrant.HIGH_VOLUME_LOW_VALUE),
        (1, 1000, a.Quadrant.LOW_VOLUME_HIGH_VALUE),
        (1, 100, a.Quadrant.LOW_VOLUME_LOW_VALUE),
    ],
)
def test_quadrant(units: int, value: int, expected: a.Quadrant) -> None:
    assert a.quadrant(units, value, 5, 500) == expected


def test_share_and_average() -> None:
    assert a.share_pct(1, 3) == 33.3
    assert a.share_pct(1, 0) is None
    assert a.rounded_average(100, 3) == 33
    assert a.rounded_average(101, 2) == 51  # half up
    assert a.rounded_average(5, 0) is None


@pytest.mark.parametrize("lead", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_safe_defuses_formulas(lead: str) -> None:
    assert a.csv_safe(f"{lead}SUM(A1)") == f"'{lead}SUM(A1)"


def test_csv_safe_leaves_normal_text() -> None:
    assert a.csv_safe("Paneer Tikka") == "Paneer Tikka"
