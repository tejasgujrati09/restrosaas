"""Owner analytics: what the restaurant sold, how fast the kitchen and floor worked, and the
rounds behind every number. Read-only apart from the expected prep time.

Definitions live next to each figure in the response (`definition`, `basis`, `excluded`) so the
screen can explain every number. Revenue, bills, tax, refunds and payment mix are not here:
they need billing (Milestone 5) and are not estimated (docs/DECISIONS.md "Owner analytics").
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import clock
from app.api.v1.common import ERRORS, Ctx, IdempotencyKeyHeader, invalid
from app.audit import audit
from app.core import analytics as core
from app.core.permissions import Capability, assert_can, can
from app.deps import OutletContext
from app.domains.analytics import queries as q
from app.domains.tenant.models import Outlet
from app.idempotency import fingerprint, run_idempotent

router = APIRouter(prefix="/v1/outlets/{outlet_id}/analytics", tags=["analytics"])

_ORDER_PAGE = 50
_EXPORT_ROW_LIMIT = 10_000


# ---------------------------------------------------------------- shared shapes


class AnalyticsRangeOut(BaseModel):
    preset: core.RangePreset
    start: date
    end: date
    days: int
    previous_start: date
    previous_end: date
    bucket: core.Bucket
    timezone: str
    generated_at: datetime


class AnalyticsKpi(BaseModel):
    """`value` is None when there is no data. `change_pct` is None unless the previous period
    has a valid, non-zero value to compare with."""

    value: float | None
    previous: float | None
    change_pct: float | None
    n: int
    previous_n: int
    unit: Literal["count", "paise", "seconds", "percent", "ratio"]
    basis: str
    definition: str
    excluded: str | None = None


@dataclass(frozen=True)
class Window:
    outlet_id: UUID
    tz_name: str
    expected_minutes: int
    current: core.DateRange
    previous: core.DateRange
    bucket: core.Bucket
    lo: datetime
    hi: datetime
    plo: datetime
    phi: datetime
    now: datetime

    def out(self, preset: core.RangePreset) -> AnalyticsRangeOut:
        return AnalyticsRangeOut(
            preset=preset,
            start=self.current.start,
            end=self.current.end,
            days=self.current.days,
            previous_start=self.previous.start,
            previous_end=self.previous.end,
            bucket=self.bucket,
            timezone=self.tz_name,
            generated_at=self.now,
        )


PresetQ = Annotated[core.RangePreset, Query(alias="range")]
StartQ = Annotated[date | None, Query(alias="from")]
EndQ = Annotated[date | None, Query(alias="to")]


async def _window(
    ctx: OutletContext,
    preset: core.RangePreset,
    start: date | None,
    end: date | None,
    capability: Capability = Capability.VIEW_ANALYTICS,
) -> Window:
    assert_can(ctx.actor, capability, ctx.outlet_id)
    outlet = await ctx.session.scalar(select(Outlet).where(Outlet.id == ctx.outlet_id))
    assert outlet is not None
    tz = ZoneInfo(outlet.timezone)
    now = clock.utcnow()
    try:
        current = core.resolve_range(preset, now.astimezone(tz).date(), start, end)
    except core.RangeError as exc:
        raise invalid("range", str(exc), "invalid_range") from exc
    previous = core.previous_range(current)
    lo, hi = core.utc_bounds(current, tz)
    plo, phi = core.utc_bounds(previous, tz)
    return Window(
        ctx.outlet_id,
        outlet.timezone,
        outlet.expected_prep_minutes,
        current,
        previous,
        core.bucket_for(current),
        lo,
        hi,
        plo,
        phi,
        now,
    )


def _kpi(
    current: float | None,
    previous: float | None,
    n: int,
    previous_n: int,
    unit: Literal["count", "paise", "seconds", "percent", "ratio"],
    basis: str,
    definition: str,
    excluded: str | None = None,
) -> AnalyticsKpi:
    return AnalyticsKpi(
        value=current,
        previous=previous,
        change_pct=core.change_pct(current, previous),
        n=n,
        previous_n=previous_n,
        unit=unit,
        basis=basis,
        definition=definition,
        excluded=excluded,
    )


def _avg(value: Any) -> float | None:
    return None if value is None else round(float(value), 1)


def _by_bucket(rows: list[q.Row]) -> dict[date, q.Row]:
    return {r["bucket"]: r for r in rows}


# ---------------------------------------------------------------- overview


class AnalyticsTrendPoint(BaseModel):
    bucket: date
    orders: int
    order_value_paise: int
    cancelled: int
    avg_prep_seconds: float | None
    prep_n: int


class AnalyticsStatusCount(BaseModel):
    status: str
    n: int


class AnalyticsHourPoint(BaseModel):
    hour: int
    orders: int
    order_value_paise: int
    tickets: int
    lines_served: int


class AnalyticsPeakWindow(BaseModel):
    start_hour: int
    end_hour: int


class AnalyticsPeakOut(BaseModel):
    by_hour: list[AnalyticsHourPoint]
    # Rounds per (weekday Mon..Sun) x (hour 0..23), local time.
    heatmap: list[list[int]]
    windows: list[AnalyticsPeakWindow]


class AnalyticsCancelledItem(BaseModel):
    name: str
    units: int
    value_paise: int


class AnalyticsCancellationsOut(BaseModel):
    rounds: int
    rate_pct: float | None
    value_paise: int
    items: list[AnalyticsCancelledItem]
    note: str


class AnalyticsOverviewKpis(BaseModel):
    orders: AnalyticsKpi
    order_value: AnalyticsKpi
    avg_order_value: AnalyticsKpi
    items_per_order: AnalyticsKpi
    avg_prep: AnalyticsKpi
    avg_ready_to_served: AnalyticsKpi
    cancellation_rate: AnalyticsKpi


class AnalyticsOverviewOut(BaseModel):
    range: AnalyticsRangeOut
    expected_prep_minutes: int
    can_edit_expected_prep: bool
    can_export: bool
    kpis: AnalyticsOverviewKpis
    pending_orders: int
    trend: list[AnalyticsTrendPoint]
    status_mix: list[AnalyticsStatusCount]
    peak: AnalyticsPeakOut
    cancellations: AnalyticsCancellationsOut


_VALUE_DEF = (
    "Sum of item price x quantity at the price locked when ordered, over items that were not "
    "cancelled or voided, on rounds that were not cancelled. It is not a bill: it has no tax, "
    "discount or service charge."
)


@router.get("/overview", responses=ERRORS)
async def overview(
    ctx: Ctx, preset: PresetQ = core.RangePreset.LAST_7_DAYS, start: StartQ = None, end: EndQ = None
) -> AnalyticsOverviewOut:
    w = await _window(ctx, preset, start, end)
    s = ctx.session
    tz = w.tz_name
    cur = await q.order_summary(s, w.outlet_id, w.lo, w.hi, tz)
    prev = await q.order_summary(s, w.outlet_id, w.plo, w.phi, tz)
    tk = await q.ticket_summary(s, w.outlet_id, w.lo, w.hi, tz, w.expected_minutes)
    tk_prev = await q.ticket_summary(s, w.outlet_id, w.plo, w.phi, tz, w.expected_minutes)
    gap = await q.serve_gap(s, w.outlet_id, w.lo, w.hi, tz)
    gap_prev = await q.serve_gap(s, w.outlet_id, w.plo, w.phi, tz)

    def rate(row: q.Row) -> float | None:
        return core.share_pct(row["cancelled"], row["placed"])

    def aov(row: q.Row) -> float | None:
        return core.rounded_average(row["value"], row["valid"])

    def ipo(row: q.Row) -> float | None:
        return round(row["units"] / row["valid"], 2) if row["valid"] else None

    kpis = AnalyticsOverviewKpis(
        orders=_kpi(
            cur["valid"],
            prev["valid"],
            cur["valid"],
            prev["valid"],
            "count",
            "rounds",
            "Rounds placed in the range that were not cancelled and have at least one item.",
            "Cancelled rounds and rounds with every item voided.",
        ),
        order_value=_kpi(
            cur["value"],
            prev["value"],
            cur["valid"],
            prev["valid"],
            "paise",
            "rounds",
            _VALUE_DEF,
        ),
        avg_order_value=_kpi(
            aov(cur),
            aov(prev),
            cur["valid"],
            prev["valid"],
            "paise",
            "rounds",
            "Order value divided by the number of rounds. A round is one submission of items "
            "on a tab, not a whole visit.",
        ),
        items_per_order=_kpi(
            ipo(cur),
            ipo(prev),
            cur["valid"],
            prev["valid"],
            "ratio",
            "rounds",
            "Total quantity of live items divided by the number of rounds.",
        ),
        avg_prep=_kpi(
            _avg(tk["avg_prep"]),
            _avg(tk_prev["avg_prep"]),
            tk["n"],
            tk_prev["n"],
            "seconds",
            "kitchen tickets",
            "Time from the kitchen or bar starting a ticket to marking it ready, averaged over "
            "tickets of rounds placed in the range. A ticket is one station's share of a round.",
            "Cancelled tickets, tickets not yet started or ready, and tickets with "
            "timestamps out of order.",
        ),
        avg_ready_to_served=_kpi(
            _avg(gap["avg_gap"]),
            _avg(gap_prev["avg_gap"]),
            gap["n"],
            gap_prev["n"],
            "seconds",
            "served items",
            "Time from a ticket being ready to a waiter marking each of its items served, "
            "averaged per item.",
            "Items not yet served.",
        ),
        cancellation_rate=_kpi(
            rate(cur),
            rate(prev),
            cur["placed"],
            prev["placed"],
            "percent",
            "rounds placed",
            "Cancelled rounds divided by all rounds placed. Today that is guests undoing "
            "within their 60 seconds; manager voids are not built yet.",
        ),
    )

    trend_rows = _by_bucket(await q.order_trend(s, w.outlet_id, w.lo, w.hi, tz, w.bucket.value))
    prep_rows = _by_bucket(await q.prep_trend(s, w.outlet_id, w.lo, w.hi, tz, w.bucket.value))
    trend = []
    for b in core.bucket_starts(w.current, w.bucket):
        row = trend_rows.get(b)
        prep = prep_rows.get(b)
        trend.append(
            AnalyticsTrendPoint(
                bucket=b,
                orders=row["orders"] if row else 0,
                order_value_paise=row["value"] if row else 0,
                cancelled=row["cancelled"] if row else 0,
                avg_prep_seconds=_avg(prep["avg_prep"]) if prep else None,
                prep_n=prep["n"] if prep else 0,
            )
        )

    heat = [[0] * 24 for _ in range(7)]
    orders_h = [0] * 24
    value_h = [0] * 24
    for r in await q.orders_by_weekday_hour(s, w.outlet_id, w.lo, w.hi, tz):
        heat[r["weekday"] - 1][r["hour"]] = r["orders"]
        orders_h[r["hour"]] += r["orders"]
        value_h[r["hour"]] += r["value"]
    tickets_h = [0] * 24
    for r in await q.tickets_by_hour(s, w.outlet_id, w.lo, w.hi, tz):
        tickets_h[r["hour"]] = r["tickets"]
    served_h = [0] * 24
    for r in await q.staff_serving_by_hour(s, w.outlet_id, w.lo, w.hi, tz):
        served_h[r["hour"]] += r["lines"]
    peak = AnalyticsPeakOut(
        by_hour=[
            AnalyticsHourPoint(
                hour=h,
                orders=orders_h[h],
                order_value_paise=value_h[h],
                tickets=tickets_h[h],
                lines_served=served_h[h],
            )
            for h in range(24)
        ],
        heatmap=heat,
        windows=[
            AnalyticsPeakWindow(start_hour=a, end_hour=b) for a, b in core.peak_windows(orders_h)
        ],
    )

    items = await q.cancelled_items(s, w.outlet_id, w.lo, w.hi, tz)
    cancellations = AnalyticsCancellationsOut(
        rounds=cur["cancelled"],
        rate_pct=rate(cur),
        value_paise=cur["cancelled_value"],
        items=[
            AnalyticsCancelledItem(name=i["name"], units=i["units"], value_paise=i["value"])
            for i in items
        ],
        note="Cancelled rounds are guest undos within 60 seconds. Manager voids and refunds "
        "will appear here once billing exists. No cancellation is attributed to a waiter.",
    )
    mix = await q.status_mix(s, w.outlet_id, w.lo, w.hi, tz)
    return AnalyticsOverviewOut(
        range=w.out(preset),
        expected_prep_minutes=w.expected_minutes,
        can_edit_expected_prep=can(ctx.actor, Capability.EDIT_EXPECTED_PREP, ctx.outlet_id),
        can_export=can(ctx.actor, Capability.EXPORT_INTEGRATIONS, ctx.outlet_id),
        kpis=kpis,
        pending_orders=cur["pending"],
        trend=trend,
        status_mix=[AnalyticsStatusCount(status=r["status"], n=r["n"]) for r in mix],
        peak=peak,
        cancellations=cancellations,
    )


# ---------------------------------------------------------------- kitchen


class AnalyticsKitchenKpis(BaseModel):
    avg_prep: AnalyticsKpi
    avg_wait: AnalyticsKpi
    avg_to_ready: AnalyticsKpi
    avg_ready_to_served: AnalyticsKpi
    over_expected: AnalyticsKpi


class AnalyticsCoverage(BaseModel):
    """How many tickets the timings could use, and why the rest were left out."""

    total: int
    used: int
    cancelled: int
    unfinished: int
    invalid: int


class AnalyticsPrepPoint(BaseModel):
    key: str
    n: int
    avg_prep_seconds: float | None


class AnalyticsPrepGroup(BaseModel):
    id: UUID | None
    name: str
    n: int
    avg_prep_seconds: float
    low_sample: bool


class AnalyticsPrepItem(AnalyticsPrepGroup):
    category: str


class AnalyticsLiveBucket(BaseModel):
    n: int
    over_expected: int
    longest_seconds: int | None


class AnalyticsLiveOut(BaseModel):
    waiting_for_kitchen: AnalyticsLiveBucket
    preparing: AnalyticsLiveBucket
    ready_awaiting_serve: AnalyticsLiveBucket


class AnalyticsKitchenOut(BaseModel):
    range: AnalyticsRangeOut
    expected_prep_minutes: int
    can_edit_expected_prep: bool
    kpis: AnalyticsKitchenKpis
    coverage: AnalyticsCoverage
    trend: list[AnalyticsPrepPoint]
    by_hour: list[AnalyticsPrepPoint]
    by_category: list[AnalyticsPrepGroup]
    slowest: list[AnalyticsPrepItem]
    fastest: list[AnalyticsPrepItem]
    items_hidden_low_sample: int
    live: AnalyticsLiveOut
    note: str


def _live_bucket(waits: list[float], expected_minutes: int, judge: bool) -> AnalyticsLiveBucket:
    over = sum(1 for x in waits if core.is_delayed(x, expected_minutes)) if judge else 0
    return AnalyticsLiveBucket(
        n=len(waits), over_expected=over, longest_seconds=int(max(waits)) if waits else None
    )


async def _live(ctx: OutletContext, w: Window) -> AnalyticsLiveOut:
    waiting: list[float] = []
    preparing: list[float] = []
    ready: list[float] = []
    for t in await q.live_tickets(ctx.session, w.outlet_id):
        if t["status"] == "queued" and t["order_status"] != "placed":
            since = t["accepted_at"] or t["created_at"]
            waiting.append(max((w.now - since).total_seconds(), 0))
        elif t["status"] == "preparing" and t["started_at"] is not None:
            preparing.append(max((w.now - t["started_at"]).total_seconds(), 0))
        elif t["status"] == "ready" and t["ready_at"] is not None:
            ready.append(max((w.now - t["ready_at"]).total_seconds(), 0))
    return AnalyticsLiveOut(
        waiting_for_kitchen=_live_bucket(waiting, w.expected_minutes, True),
        preparing=_live_bucket(preparing, w.expected_minutes, True),
        # Nothing defines how long a ready order may wait, so it is counted, never judged.
        ready_awaiting_serve=_live_bucket(ready, w.expected_minutes, False),
    )


@router.get("/kitchen", responses=ERRORS)
async def kitchen(
    ctx: Ctx, preset: PresetQ = core.RangePreset.LAST_7_DAYS, start: StartQ = None, end: EndQ = None
) -> AnalyticsKitchenOut:
    w = await _window(ctx, preset, start, end)
    s, tz, exp = ctx.session, w.tz_name, w.expected_minutes
    cur = await q.ticket_summary(s, w.outlet_id, w.lo, w.hi, tz, exp)
    prev = await q.ticket_summary(s, w.outlet_id, w.plo, w.phi, tz, exp)
    gap = await q.serve_gap(s, w.outlet_id, w.lo, w.hi, tz)
    gap_prev = await q.serve_gap(s, w.outlet_id, w.plo, w.phi, tz)
    excl = (
        "Cancelled tickets, tickets not yet started or ready, and tickets with timestamps "
        "out of order."
    )

    def over(row: q.Row) -> float | None:
        return core.share_pct(row["over_expected"], row["n"])

    kpis = AnalyticsKitchenKpis(
        avg_prep=_kpi(
            _avg(cur["avg_prep"]),
            _avg(prev["avg_prep"]),
            cur["n"],
            prev["n"],
            "seconds",
            "kitchen tickets",
            "Ticket ready time minus ticket start time.",
            excl,
        ),
        avg_wait=_kpi(
            _avg(cur["avg_wait"]),
            _avg(prev["avg_wait"]),
            cur["n"],
            prev["n"],
            "seconds",
            "kitchen tickets",
            "Time a ticket waited between the round being accepted and the kitchen starting it. "
            "Auto-accepted rounds are accepted 60 seconds after placing.",
            excl,
        ),
        avg_to_ready=_kpi(
            _avg(cur["avg_to_ready"]),
            _avg(prev["avg_to_ready"]),
            cur["n"],
            prev["n"],
            "seconds",
            "kitchen tickets",
            "Time from the guest placing the round to the ticket being ready: what the guest "
            "waits, including the undo window.",
            excl,
        ),
        avg_ready_to_served=_kpi(
            _avg(gap["avg_gap"]),
            _avg(gap_prev["avg_gap"]),
            gap["n"],
            gap_prev["n"],
            "seconds",
            "served items",
            "Time from the ticket being ready to each item being marked served.",
            "Items not yet served.",
        ),
        over_expected=_kpi(
            over(cur),
            over(prev),
            cur["n"],
            prev["n"],
            "percent",
            "kitchen tickets",
            f"Share of finished tickets whose prep time was longer than the outlet's expected "
            f"{exp} minutes.",
            excl,
        ),
    )
    trend_rows = _by_bucket(await q.prep_trend(s, w.outlet_id, w.lo, w.hi, tz, w.bucket.value))
    trend = [
        AnalyticsPrepPoint(
            key=b.isoformat(),
            n=trend_rows[b]["n"] if b in trend_rows else 0,
            avg_prep_seconds=_avg(trend_rows[b]["avg_prep"]) if b in trend_rows else None,
        )
        for b in core.bucket_starts(w.current, w.bucket)
    ]
    hours = {r["hour"]: r for r in await q.prep_by_hour(s, w.outlet_id, w.lo, w.hi, tz)}
    by_hour = [
        AnalyticsPrepPoint(
            key=str(h),
            n=hours[h]["n"] if h in hours else 0,
            avg_prep_seconds=_avg(hours[h]["avg_prep"]) if h in hours else None,
        )
        for h in range(24)
    ]
    cats = [
        AnalyticsPrepGroup(
            id=r["id"],
            name=r["name"],
            n=r["n"],
            avg_prep_seconds=_avg(r["avg_prep"]) or 0.0,
            low_sample=core.low_sample(r["n"]),
        )
        for r in await q.prep_by_category(s, w.outlet_id, w.lo, w.hi, tz)
    ]
    cats.sort(key=lambda c: -c.avg_prep_seconds)
    items = [
        AnalyticsPrepItem(
            id=r["id"],
            name=r["name"],
            category=r["category"],
            n=r["n"],
            avg_prep_seconds=_avg(r["avg_prep"]) or 0.0,
            low_sample=core.low_sample(r["n"]),
        )
        for r in await q.prep_by_item(s, w.outlet_id, w.lo, w.hi, tz)
    ]
    ranked = [i for i in items if not i.low_sample]
    ranked.sort(key=lambda i: (-i.avg_prep_seconds, i.name))
    return AnalyticsKitchenOut(
        range=w.out(preset),
        expected_prep_minutes=exp,
        can_edit_expected_prep=can(ctx.actor, Capability.EDIT_EXPECTED_PREP, ctx.outlet_id),
        kpis=kpis,
        coverage=AnalyticsCoverage(
            total=cur["total"],
            used=cur["n"],
            cancelled=cur["cancelled"],
            unfinished=cur["unfinished"],
            invalid=cur["invalid"],
        ),
        trend=trend,
        by_hour=by_hour,
        by_category=cats,
        slowest=ranked[:10],
        fastest=list(reversed(ranked[-10:])),
        items_hidden_low_sample=len(items) - len(ranked),
        live=await _live(ctx, w),
        note="Kitchens work in tickets (one per station per round), so an item's prep time is "
        f"the time of the tickets it was on. Items with fewer than {core.MIN_SAMPLES} tickets "
        "are not ranked.",
    )


# ---------------------------------------------------------------- staff


class AnalyticsStaffRowOut(BaseModel):
    user_id: UUID
    name: str
    role: str | None
    lines_served: int
    units_served: int
    rounds_served: int
    tables_served: int
    order_value_served_paise: int
    avg_ready_to_served_seconds: float | None
    ready_to_served_n: int
    active_days: int
    lines_per_active_day: float | None
    rounds_entered: int
    order_value_entered_paise: int
    peak_hour: int | None
    peak_hour_lines: int


class AnalyticsStaffHour(BaseModel):
    hour: int
    lines_served: int
    staff_active: int
    lines_per_staff: float | None


class AnalyticsStaffOut(BaseModel):
    range: AnalyticsRangeOut
    can_export: bool
    rows: list[AnalyticsStaffRowOut]
    by_hour: list[AnalyticsStaffHour]
    notes: list[str]


@router.get("/staff", responses=ERRORS)
async def staff(
    ctx: Ctx, preset: PresetQ = core.RangePreset.LAST_7_DAYS, start: StartQ = None, end: EndQ = None
) -> AnalyticsStaffOut:
    w = await _window(ctx, preset, start, end)
    s, tz = ctx.session, w.tz_name
    served = {r["user_id"]: r for r in await q.staff_serving(s, w.outlet_id, w.lo, w.hi, tz)}
    placed = {r["user_id"]: r for r in await q.staff_placed(s, w.outlet_id, w.lo, w.hi, tz)}
    hourly = await q.staff_serving_by_hour(s, w.outlet_id, w.lo, w.hi, tz)
    ids = sorted(set(served) | set(placed), key=str)
    names = {r["id"]: r for r in await q.staff_names(s, w.outlet_id, ids)}

    peak: dict[UUID, tuple[int, int]] = {}
    lines_h = [0] * 24
    active_h: list[set[UUID]] = [set() for _ in range(24)]
    for r in hourly:
        lines_h[r["hour"]] += r["lines"]
        active_h[r["hour"]].add(r["user_id"])
        best = peak.get(r["user_id"])
        if best is None or r["lines"] > best[1]:
            peak[r["user_id"]] = (r["hour"], r["lines"])

    rows = []
    for uid in ids:
        sv = served.get(uid)
        pl = placed.get(uid)
        who = names.get(uid)
        lines = sv["lines"] if sv else 0
        days = sv["active_days"] if sv else 0
        rows.append(
            AnalyticsStaffRowOut(
                user_id=uid,
                name=(who["name"] if who and who["name"] else "Unnamed"),
                role=who["role"] if who else None,
                lines_served=lines,
                units_served=sv["units"] if sv else 0,
                rounds_served=sv["rounds"] if sv else 0,
                tables_served=sv["tables"] if sv else 0,
                order_value_served_paise=sv["value"] if sv else 0,
                avg_ready_to_served_seconds=_avg(sv["gap_avg"]) if sv else None,
                ready_to_served_n=sv["gap_n"] if sv else 0,
                active_days=days,
                lines_per_active_day=round(lines / days, 1) if days else None,
                rounds_entered=pl["rounds"] if pl else 0,
                order_value_entered_paise=pl["value"] if pl else 0,
                peak_hour=peak[uid][0] if uid in peak else None,
                peak_hour_lines=peak[uid][1] if uid in peak else 0,
            )
        )
    rows.sort(key=lambda r: (-r.lines_served, r.name))
    return AnalyticsStaffOut(
        range=w.out(preset),
        can_export=can(ctx.actor, Capability.EXPORT_INTEGRATIONS, ctx.outlet_id),
        rows=rows,
        by_hour=[
            AnalyticsStaffHour(
                hour=h,
                lines_served=lines_h[h],
                staff_active=len(active_h[h]),
                lines_per_staff=round(lines_h[h] / len(active_h[h]), 1) if active_h[h] else None,
            )
            for h in range(24)
        ],
        notes=[
            "Served items, rounds and tables are credited to whoever marked the item served, "
            "for items served in the range.",
            "Rounds entered counts only rounds a staff member typed in; guest-placed rounds "
            "have no waiter.",
            "Order value is at locked prices, not billed amounts. Bills and average bill per "
            "waiter will appear once billing exists.",
            "Volume differs with the tables and shifts someone covers, so compare lines per "
            "active day and the time to serve, not totals alone.",
            "Cancellations are not attributed to a waiter: the data does not show who caused one.",
        ],
    )


# ---------------------------------------------------------------- menu


class AnalyticsMenuItemOut(BaseModel):
    id: UUID
    name: str
    category: str
    category_id: UUID | None
    rounds: int
    units: int
    order_value_paise: int
    share_pct: float | None
    avg_price_paise: int | None
    dropped_units: int
    dropped_rate_pct: float | None
    avg_prep_seconds: float | None
    prep_n: int
    quadrant: core.Quadrant


class AnalyticsMenuCategoryOut(BaseModel):
    id: UUID | None
    name: str
    rounds: int
    units: int
    order_value_paise: int
    share_pct: float | None
    avg_order_value_paise: int | None


class AnalyticsMenuOut(BaseModel):
    range: AnalyticsRangeOut
    can_export: bool
    total_units: int
    total_order_value_paise: int
    median_units: float | None
    median_order_value_paise: float | None
    items: list[AnalyticsMenuItemOut]
    categories: list[AnalyticsMenuCategoryOut]
    notes: list[str]


@router.get("/menu", responses=ERRORS)
async def menu(
    ctx: Ctx,
    preset: PresetQ = core.RangePreset.LAST_30_DAYS,
    start: StartQ = None,
    end: EndQ = None,
) -> AnalyticsMenuOut:
    w = await _window(ctx, preset, start, end)
    s, tz = ctx.session, w.tz_name
    rows = [r for r in await q.menu_items(s, w.outlet_id, w.lo, w.hi, tz)]
    prep = {r["id"]: r for r in await q.prep_by_item(s, w.outlet_id, w.lo, w.hi, tz)}
    total_units = sum(r["units"] for r in rows)
    total_value = sum(r["value"] for r in rows)
    sold = [r for r in rows if r["units"] > 0]
    med_u = core.median([r["units"] for r in sold])
    med_v = core.median([r["value"] for r in sold])
    items = []
    for r in sold + [r for r in rows if r["units"] == 0]:
        p = prep.get(r["id"])
        ordered = r["units"] + r["dropped_units"]
        items.append(
            AnalyticsMenuItemOut(
                id=r["id"],
                name=r["name"],
                category=r["category"],
                category_id=r["category_id"],
                rounds=r["rounds"],
                units=r["units"],
                order_value_paise=r["value"],
                share_pct=core.share_pct(r["value"], total_value),
                avg_price_paise=core.rounded_average(r["value"], r["units"]),
                dropped_units=r["dropped_units"],
                dropped_rate_pct=core.share_pct(r["dropped_units"], ordered),
                avg_prep_seconds=_avg(p["avg_prep"]) if p else None,
                prep_n=p["n"] if p else 0,
                quadrant=core.quadrant(r["units"], r["value"], med_u or 0, med_v or 0),
            )
        )
    items.sort(key=lambda i: (-i.order_value_paise, i.name))
    cats = [
        AnalyticsMenuCategoryOut(
            id=r["id"],
            name=r["name"],
            rounds=r["rounds"],
            units=r["units"],
            order_value_paise=r["value"],
            share_pct=core.share_pct(r["value"], total_value),
            avg_order_value_paise=core.rounded_average(r["value"], r["rounds"]),
        )
        for r in await q.menu_categories(s, w.outlet_id, w.lo, w.hi, tz)
    ]
    cats.sort(key=lambda c: (-c.order_value_paise, c.name))
    return AnalyticsMenuOut(
        range=w.out(preset),
        can_export=can(ctx.actor, Capability.EXPORT_INTEGRATIONS, ctx.outlet_id),
        total_units=total_units,
        total_order_value_paise=total_value,
        median_units=med_u,
        median_order_value_paise=med_v,
        items=items[:500],
        categories=cats,
        notes=[
            "Most ordered is by units; highest value is by order value. They can differ.",
            "Order value is at locked prices before tax, discount and service charge.",
            "The four groups compare each item with the median item on this menu for the range. "
            "They describe position only; what they mean is your call.",
            "Prep time is the time of the kitchen tickets the item was on, not the item alone.",
        ],
    )


# ---------------------------------------------------------------- tables


class AnalyticsTableRowOut(BaseModel):
    id: UUID
    label: str
    zone: str
    seats: int
    visits: int
    rounds: int
    order_value_paise: int
    avg_round_value_paise: int | None
    guests: int


class AnalyticsTablesOut(BaseModel):
    range: AnalyticsRangeOut
    rows: list[AnalyticsTableRowOut]
    notes: list[str]


@router.get("/tables", responses=ERRORS)
async def tables(
    ctx: Ctx,
    preset: PresetQ = core.RangePreset.LAST_30_DAYS,
    start: StartQ = None,
    end: EndQ = None,
) -> AnalyticsTablesOut:
    w = await _window(ctx, preset, start, end)
    rows = [
        AnalyticsTableRowOut(
            id=r["id"],
            label=r["label"],
            zone=r["zone"],
            seats=r["seats"],
            visits=r["visits"],
            rounds=r["rounds"],
            order_value_paise=r["value"],
            avg_round_value_paise=core.rounded_average(r["value"], r["rounds"]),
            guests=r["guests"],
        )
        for r in await q.table_activity(ctx.session, w.outlet_id, w.lo, w.hi, w.tz_name)
    ]
    rows.sort(key=lambda r: (-r.order_value_paise, r.label))
    return AnalyticsTablesOut(
        range=w.out(preset),
        rows=rows,
        notes=[
            "A visit is a tab with at least one round in the range, on the table it is at now "
            "(a transferred or merged tab counts on its current table).",
            "Table turnaround and utilisation need the time a tab closes, which arrives with "
            "billing. They are not estimated.",
        ],
    )


# ---------------------------------------------------------------- drill-down


class AnalyticsOrderRowOut(BaseModel):
    id: UUID
    tab_id: UUID
    seq_no: int
    status: str
    source: str
    placed_at: datetime
    table_label: str | None
    order_value_paise: int
    items: str | None
    prep_seconds: float | None
    delayed: bool
    served_by: str | None


class AnalyticsOrdersOut(BaseModel):
    range: AnalyticsRangeOut
    rows: list[AnalyticsOrderRowOut]
    next_cursor: str | None


class AnalyticsOrderFilters(BaseModel):
    status: str | None = None
    item_id: UUID | None = None
    category_id: UUID | None = None
    served_by: UUID | None = None
    table_id: UUID | None = None
    weekday: int | None = Field(default=None, ge=1, le=7)
    hour: int | None = Field(default=None, ge=0, le=23)
    day: date | None = None
    delayed: bool = False


def _encode(at: datetime, order_id: UUID) -> str:
    return f"{at.isoformat()}|{order_id}"


def _decode(cursor: str) -> tuple[datetime, UUID]:
    try:
        at, _, oid = cursor.partition("|")
        return datetime.fromisoformat(at), UUID(oid)
    except ValueError as exc:
        raise invalid("cursor", "That page marker is not valid.", "invalid_cursor") from exc


async def _order_rows(
    ctx: OutletContext,
    w: Window,
    f: AnalyticsOrderFilters,
    limit: int,
    cursor: str | None,
) -> tuple[list[AnalyticsOrderRowOut], str | None]:
    rows = await q.order_list(
        ctx.session,
        w.outlet_id,
        w.lo,
        w.hi,
        w.tz_name,
        w.expected_minutes,
        limit=limit,
        cursor=_decode(cursor) if cursor else None,
        **f.model_dump(),
    )
    more = len(rows) > limit
    page = rows[:limit]
    out = [
        AnalyticsOrderRowOut(
            id=r["id"],
            tab_id=r["tab_id"],
            seq_no=r["seq_no"],
            status=r["status"],
            source=r["source"],
            placed_at=r["placed_at"],
            table_label=r["table_label"],
            order_value_paise=r["value"],
            items=r["items"],
            prep_seconds=_avg(r["prep"]),
            delayed=r["prep"] is not None and core.is_delayed(float(r["prep"]), w.expected_minutes),
            served_by=r["served_by"],
        )
        for r in page
    ]
    return out, (_encode(page[-1]["placed_at"], page[-1]["id"]) if more else None)


def _filters(
    status: str | None,
    item_id: UUID | None,
    category_id: UUID | None,
    served_by: UUID | None,
    table_id: UUID | None,
    weekday: int | None,
    hour: int | None,
    day: date | None,
    delayed: bool,
) -> AnalyticsOrderFilters:
    return AnalyticsOrderFilters(
        status=status,
        item_id=item_id,
        category_id=category_id,
        served_by=served_by,
        table_id=table_id,
        weekday=weekday,
        hour=hour,
        day=day,
        delayed=delayed,
    )


@router.get("/orders", responses=ERRORS)
async def orders(
    ctx: Ctx,
    preset: PresetQ = core.RangePreset.LAST_7_DAYS,
    start: StartQ = None,
    end: EndQ = None,
    status: str | None = None,
    item_id: UUID | None = None,
    category_id: UUID | None = None,
    served_by: UUID | None = None,
    table_id: UUID | None = None,
    weekday: Annotated[int | None, Query(ge=1, le=7)] = None,
    hour: Annotated[int | None, Query(ge=0, le=23)] = None,
    day: date | None = None,
    delayed: bool = False,
    cursor: str | None = None,
) -> AnalyticsOrdersOut:
    """The rounds behind a dashboard number, newest first, 50 per page."""
    w = await _window(ctx, preset, start, end)
    f = _filters(status, item_id, category_id, served_by, table_id, weekday, hour, day, delayed)
    rows, nxt = await _order_rows(ctx, w, f, _ORDER_PAGE, cursor)
    return AnalyticsOrdersOut(range=w.out(preset), rows=rows, next_cursor=nxt)


# ---------------------------------------------------------------- export


def _csv(header: list[str], rows: list[list[Any]]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow([core.csv_safe(c) if isinstance(c, str) else c for c in row])
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="analytics.csv"'},
    )


def _rupees(paise: int | None) -> str:
    """CSV cells carry plain rupees ('123.50') so a spreadsheet can total them."""
    return "" if paise is None else f"{paise // 100}.{paise % 100:02d}"


@router.get("/export/{kind}", responses=ERRORS)
async def export(
    ctx: Ctx,
    kind: Literal["orders", "staff", "menu"],
    preset: PresetQ = core.RangePreset.LAST_7_DAYS,
    start: StartQ = None,
    end: EndQ = None,
) -> Response:
    """CSV of what the matching screen shows. Owner only, like every export (SPEC §6)."""
    w = await _window(ctx, preset, start, end, Capability.EXPORT_INTEGRATIONS)
    if kind == "orders":
        out: list[AnalyticsOrderRowOut] = []
        cursor: str | None = None
        while len(out) < _EXPORT_ROW_LIMIT:
            page, cursor = await _order_rows(ctx, w, AnalyticsOrderFilters(), 1000, cursor)
            out += page
            if cursor is None:
                break
        tz = ZoneInfo(w.tz_name)
        return _csv(
            [
                "Placed at (local)",
                "Table",
                "Round",
                "Status",
                "Source",
                "Items",
                "Order value (INR)",
                "Prep seconds",
                "Served by",
            ],
            [
                [
                    o.placed_at.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                    o.table_label or "",
                    o.seq_no,
                    o.status,
                    o.source,
                    o.items or "",
                    _rupees(o.order_value_paise),
                    "" if o.prep_seconds is None else round(o.prep_seconds),
                    o.served_by or "",
                ]
                for o in out
            ],
        )
    if kind == "staff":
        st = await staff(ctx, preset, start, end)
        return _csv(
            [
                "Name",
                "Role",
                "Items served",
                "Rounds served",
                "Tables served",
                "Active days",
                "Items per active day",
                "Avg ready to served (s)",
                "Items timed",
                "Order value served (INR)",
                "Rounds entered",
            ],
            [
                [
                    r.name,
                    r.role or "",
                    r.lines_served,
                    r.rounds_served,
                    r.tables_served,
                    r.active_days,
                    r.lines_per_active_day or "",
                    r.avg_ready_to_served_seconds or "",
                    r.ready_to_served_n,
                    _rupees(r.order_value_served_paise),
                    r.rounds_entered,
                ]
                for r in st.rows
            ],
        )
    mn = await menu(ctx, preset, start, end)
    return _csv(
        [
            "Item",
            "Category",
            "Rounds",
            "Units",
            "Order value (INR)",
            "Share of value %",
            "Avg price (INR)",
            "Cancelled or voided units",
            "Avg prep (s)",
            "Prep tickets",
        ],
        [
            [
                i.name,
                i.category,
                i.rounds,
                i.units,
                _rupees(i.order_value_paise),
                i.share_pct or "",
                _rupees(i.avg_price_paise),
                i.dropped_units,
                i.avg_prep_seconds or "",
                i.prep_n,
            ]
            for i in mn.items
        ],
    )


# ---------------------------------------------------------------- expected prep time


class AnalyticsExpectedPrepIn(BaseModel):
    minutes: int = Field(ge=1, le=240)


class AnalyticsExpectedPrepOut(BaseModel):
    expected_prep_minutes: int


@router.put("/expected-prep", responses=ERRORS)
async def set_expected_prep(
    ctx: Ctx, key: IdempotencyKeyHeader, body: Annotated[AnalyticsExpectedPrepIn, Body()]
) -> AnalyticsExpectedPrepOut:
    """The outlet-wide yardstick for a delayed order. Owner or manager."""
    assert_can(ctx.actor, Capability.EDIT_EXPECTED_PREP, ctx.outlet_id)
    return await run_idempotent(
        ctx.session,
        ctx.restaurant_id,
        ctx.actor.user_id,
        key,
        fingerprint("PUT", f"expected-prep/{ctx.outlet_id}", body.model_dump()),
        AnalyticsExpectedPrepOut,
        lambda: _apply_expected_prep(ctx, body),
    )


async def _apply_expected_prep(
    ctx: OutletContext, body: AnalyticsExpectedPrepIn
) -> AnalyticsExpectedPrepOut:
    outlet = await ctx.session.get(Outlet, ctx.outlet_id)
    assert outlet is not None
    before = outlet.expected_prep_minutes
    outlet.expected_prep_minutes = body.minutes
    audit(
        ctx,
        "outlet.expected_prep_minutes.update",
        "outlet",
        ctx.outlet_id,
        {"expected_prep_minutes": before},
        {"expected_prep_minutes": body.minutes},
    )
    return AnalyticsExpectedPrepOut(expected_prep_minutes=body.minutes)
