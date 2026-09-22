"""SQL behind the owner analytics screens. One function per question, each a plain
aggregation the owner could reproduce by hand from `tab_order`, `order_line` and `ticket`.

Common rules (docs/DECISIONS.md "Owner analytics"):

* A range is a half-open UTC interval `[lo, hi)`; hour, weekday and day buckets are taken in
  the outlet's timezone (`tz`).
* Orders and order value are cohorted by `tab_order.placed_at`; kitchen timings by
  `ticket.created_at` (the round they belong to); serving work by `order_line.served_at`.
* "Order value" is the sum of `order_line.line_total` (locked prices) over lines that are not
  cancelled or voided, on rounds that are not cancelled. It is not a bill: no tax, discount
  or service charge is applied.
* Every query filters on `outlet_id`; row-level security filters on the restaurant.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Row = dict[str, Any]

_GONE = "('cancelled', 'voided')"

# One row per round in range, with its value over live lines.
_ORDERS = f"""
orders AS (
  SELECT o.id, o.tab_id, o.status, o.source, o.placed_by_user_id, o.placed_at,
         o.placed_at AT TIME ZONE :tz AS placed_local,
         COALESCE(SUM(l.line_total) FILTER (WHERE l.status NOT IN {_GONE}), 0) AS value,
         COALESCE(SUM(l.qty) FILTER (WHERE l.status NOT IN {_GONE}), 0) AS units,
         COALESCE(SUM(l.line_total) FILTER (WHERE l.status IN {_GONE}), 0) AS dropped_value
    FROM tab_order o
    LEFT JOIN order_line l ON l.order_id = o.id
   WHERE o.outlet_id = :outlet AND o.placed_at >= :lo AND o.placed_at < :hi
   GROUP BY o.id
)"""

# One row per ticket whose round was placed in range. `ok` marks the tickets whose timings can
# be trusted: not cancelled, started and ready both recorded, and in that order.
_TICKETS = """
tk AS (
  SELECT t.id, t.order_id, t.status, t.created_at, t.started_at, t.ready_at,
         t.created_at AT TIME ZONE :tz AS created_local,
         (t.status <> 'cancelled' AND t.started_at IS NOT NULL AND t.ready_at IS NOT NULL
          AND t.ready_at >= t.started_at) AS ok,
         extract(epoch FROM t.ready_at - t.started_at) AS raw_prep,
         extract(epoch FROM t.started_at - COALESCE(o.accepted_at, t.created_at)) AS raw_wait,
         extract(epoch FROM t.ready_at - o.placed_at) AS raw_to_ready
    FROM ticket t
    JOIN tab_order o ON o.id = t.order_id
   WHERE t.outlet_id = :outlet AND t.created_at >= :lo AND t.created_at < :hi
)"""

_TK_COLUMNS = """
  tk.*,
  CASE WHEN ok THEN raw_prep END AS prep,
  CASE WHEN ok THEN GREATEST(raw_wait, 0) END AS wait,
  CASE WHEN ok THEN raw_to_ready END AS to_ready"""


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


async def _rows(session: AsyncSession, sql: str, params: dict[str, Any]) -> list[Row]:
    result = await session.execute(text(sql), params)
    return [dict(r) for r in result.mappings()]


def _window(outlet_id: UUID, lo: datetime, hi: datetime, tz: str, **extra: Any) -> dict[str, Any]:
    return {"outlet": outlet_id, "lo": lo, "hi": hi, "tz": tz, **extra}


async def order_summary(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> Row:
    rows = await _rows(
        session,
        f"""
        WITH {_ORDERS}
        SELECT count(*) AS placed,
               count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
               count(*) FILTER (WHERE status <> 'cancelled' AND units > 0) AS valid,
               count(*) FILTER (WHERE status NOT IN ('served', 'cancelled')) AS pending,
               COALESCE(SUM(value) FILTER (WHERE status <> 'cancelled'), 0) AS value,
               COALESCE(SUM(units) FILTER (WHERE status <> 'cancelled'), 0) AS units,
               COALESCE(SUM(dropped_value) FILTER (WHERE status = 'cancelled'), 0)
                 AS cancelled_value
          FROM orders""",
        _window(outlet_id, lo, hi, tz),
    )
    return rows[0]


async def status_mix(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    return await _rows(
        session,
        f"WITH {_ORDERS} SELECT status, count(*) AS n FROM orders GROUP BY status",
        _window(outlet_id, lo, hi, tz),
    )


async def order_trend(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str, bucket: str
) -> list[Row]:
    return await _rows(
        session,
        f"""
        WITH {_ORDERS}
        SELECT date_trunc(:bucket, placed_local)::date AS bucket,
               count(*) FILTER (WHERE status <> 'cancelled' AND units > 0) AS orders,
               COALESCE(SUM(value) FILTER (WHERE status <> 'cancelled'), 0) AS value,
               count(*) FILTER (WHERE status = 'cancelled') AS cancelled
          FROM orders GROUP BY 1 ORDER BY 1""",
        _window(outlet_id, lo, hi, tz, bucket=bucket),
    )


async def orders_by_weekday_hour(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    return await _rows(
        session,
        f"""
        WITH {_ORDERS}
        SELECT extract(isodow FROM placed_local)::int AS weekday,
               extract(hour FROM placed_local)::int AS hour,
               count(*) AS orders,
               COALESCE(SUM(value), 0) AS value
          FROM orders
         WHERE status <> 'cancelled' AND units > 0
         GROUP BY 1, 2""",
        _window(outlet_id, lo, hi, tz),
    )


async def tickets_by_hour(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    return await _rows(
        session,
        f"""
        WITH {_TICKETS}
        SELECT extract(hour FROM created_local)::int AS hour, count(*) AS tickets
          FROM tk WHERE status <> 'cancelled' GROUP BY 1""",
        _window(outlet_id, lo, hi, tz),
    )


async def cancelled_items(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    return await _rows(
        session,
        f"""
        SELECT l.item_name_snapshot AS name, SUM(l.qty)::int AS units,
               SUM(l.line_total) AS value
          FROM order_line l JOIN tab_order o ON o.id = l.order_id
         WHERE o.outlet_id = :outlet AND o.placed_at >= :lo AND o.placed_at < :hi
           AND l.status IN {_GONE}
         GROUP BY l.item_name_snapshot
         ORDER BY units DESC, name LIMIT 10""",
        _window(outlet_id, lo, hi, tz),
    )


async def ticket_summary(
    session: AsyncSession,
    outlet_id: UUID,
    lo: datetime,
    hi: datetime,
    tz: str,
    expected_minutes: int,
) -> Row:
    rows = await _rows(
        session,
        f"""
        WITH {_TICKETS}, t2 AS (SELECT {_TK_COLUMNS} FROM tk)
        SELECT count(*) AS total,
               count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
               count(*) FILTER (WHERE status <> 'cancelled'
                                  AND (started_at IS NULL OR ready_at IS NULL)) AS unfinished,
               count(*) FILTER (WHERE status <> 'cancelled' AND started_at IS NOT NULL
                                  AND ready_at IS NOT NULL AND ready_at < started_at) AS invalid,
               count(prep) AS n,
               avg(prep) AS avg_prep,
               avg(wait) AS avg_wait,
               avg(to_ready) AS avg_to_ready,
               count(*) FILTER (WHERE prep > :expected_s) AS over_expected
          FROM t2""",
        _window(outlet_id, lo, hi, tz, expected_s=expected_minutes * 60),
    )
    return rows[0]


async def serve_gap(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> Row:
    """Ready to served, per served line, for rounds placed in range."""
    rows = await _rows(
        session,
        """
        SELECT count(*) AS n,
               avg(extract(epoch FROM l.served_at - t.ready_at)) AS avg_gap
          FROM order_line l
          JOIN ticket t ON t.id = l.ticket_id
         WHERE t.outlet_id = :outlet AND t.created_at >= :lo AND t.created_at < :hi
           AND l.served_at IS NOT NULL AND t.ready_at IS NOT NULL
           AND l.served_at >= t.ready_at""",
        _window(outlet_id, lo, hi, tz),
    )
    return rows[0]


async def prep_trend(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str, bucket: str
) -> list[Row]:
    return await _rows(
        session,
        f"""
        WITH {_TICKETS}, t2 AS (SELECT {_TK_COLUMNS} FROM tk)
        SELECT date_trunc(:bucket, created_local)::date AS bucket,
               count(prep) AS n, avg(prep) AS avg_prep
          FROM t2 GROUP BY 1 ORDER BY 1""",
        _window(outlet_id, lo, hi, tz, bucket=bucket),
    )


async def prep_by_hour(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    return await _rows(
        session,
        f"""
        WITH {_TICKETS}, t2 AS (SELECT {_TK_COLUMNS} FROM tk)
        SELECT extract(hour FROM created_local)::int AS hour,
               count(prep) AS n, avg(prep) AS avg_prep
          FROM t2 GROUP BY 1""",
        _window(outlet_id, lo, hi, tz),
    )


async def prep_by_item(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    """A ticket is one station's share of a round, so an item's prep time is the time of the
    tickets it was on (each ticket counted once per item)."""
    return await _rows(
        session,
        f"""
        WITH {_TICKETS}, t2 AS (SELECT {_TK_COLUMNS} FROM tk),
        pairs AS (
          SELECT DISTINCT t2.id AS ticket_id, l.menu_item_id, t2.prep
            FROM t2 JOIN order_line l ON l.ticket_id = t2.id
           WHERE t2.prep IS NOT NULL AND l.status NOT IN {_GONE}
        )
        SELECT mi.id, mi.name, c.id AS category_id,
               COALESCE(c.name, 'Uncategorised') AS category,
               count(*) AS n, avg(p.prep) AS avg_prep
          FROM pairs p
          JOIN menu_item mi ON mi.id = p.menu_item_id
          LEFT JOIN menu_category c ON c.id = mi.category_id
         GROUP BY mi.id, mi.name, c.id, c.name""",
        _window(outlet_id, lo, hi, tz),
    )


async def prep_by_category(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    return await _rows(
        session,
        f"""
        WITH {_TICKETS}, t2 AS (SELECT {_TK_COLUMNS} FROM tk),
        pairs AS (
          SELECT DISTINCT t2.id AS ticket_id, mi.category_id, t2.prep
            FROM t2
            JOIN order_line l ON l.ticket_id = t2.id
            JOIN menu_item mi ON mi.id = l.menu_item_id
           WHERE t2.prep IS NOT NULL AND l.status NOT IN {_GONE}
        )
        SELECT c.id, COALESCE(c.name, 'Uncategorised') AS name,
               count(*) AS n, avg(p.prep) AS avg_prep
          FROM pairs p LEFT JOIN menu_category c ON c.id = p.category_id
         GROUP BY c.id, c.name""",
        _window(outlet_id, lo, hi, tz),
    )


async def live_tickets(session: AsyncSession, outlet_id: UUID) -> list[Row]:
    """Tickets still in the kitchen or waiting to be served, right now (not range-bound)."""
    return await _rows(
        session,
        """
        SELECT t.id, t.status, t.created_at, t.started_at, t.ready_at, o.accepted_at,
               o.status AS order_status
          FROM ticket t JOIN tab_order o ON o.id = t.order_id
         WHERE t.outlet_id = :outlet AND t.status IN ('queued', 'preparing', 'ready')
           AND o.status <> 'cancelled'
         LIMIT 1000""",
        {"outlet": outlet_id},
    )


async def staff_serving(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    """Work done by whoever marked lines served, for lines served in range."""
    return await _rows(
        session,
        """
        SELECT l.served_by AS user_id,
               count(*) AS lines, COALESCE(SUM(l.qty), 0) AS units,
               COALESCE(SUM(l.line_total), 0) AS value,
               count(DISTINCT l.order_id) AS rounds,
               count(DISTINCT tb.table_id) AS tables,
               count(DISTINCT (l.served_at AT TIME ZONE :tz)::date) AS active_days,
               count(*) FILTER (WHERE t.ready_at IS NOT NULL AND l.served_at >= t.ready_at)
                 AS gap_n,
               avg(extract(epoch FROM l.served_at - t.ready_at))
                 FILTER (WHERE t.ready_at IS NOT NULL AND l.served_at >= t.ready_at) AS gap_avg
          FROM order_line l
          JOIN tab_order o ON o.id = l.order_id
          JOIN tab tb ON tb.id = l.tab_id
          LEFT JOIN ticket t ON t.id = l.ticket_id
         WHERE o.outlet_id = :outlet AND l.served_at >= :lo AND l.served_at < :hi
           AND l.served_by IS NOT NULL AND l.status = 'served'
         GROUP BY l.served_by""",
        _window(outlet_id, lo, hi, tz),
    )


async def staff_serving_by_hour(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    return await _rows(
        session,
        """
        SELECT l.served_by AS user_id,
               extract(hour FROM l.served_at AT TIME ZONE :tz)::int AS hour,
               count(*) AS lines
          FROM order_line l JOIN tab_order o ON o.id = l.order_id
         WHERE o.outlet_id = :outlet AND l.served_at >= :lo AND l.served_at < :hi
           AND l.served_by IS NOT NULL AND l.status = 'served'
         GROUP BY 1, 2""",
        _window(outlet_id, lo, hi, tz),
    )


async def staff_placed(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    """Rounds a staff member entered themselves. Guest-placed rounds have no waiter."""
    return await _rows(
        session,
        f"""
        WITH {_ORDERS}
        SELECT placed_by_user_id AS user_id, count(*) AS rounds,
               COALESCE(SUM(value), 0) AS value
          FROM orders
         WHERE source = 'waiter' AND placed_by_user_id IS NOT NULL
           AND status <> 'cancelled' AND units > 0
         GROUP BY 1""",
        _window(outlet_id, lo, hi, tz),
    )


async def staff_names(session: AsyncSession, outlet_id: UUID, user_ids: list[UUID]) -> list[Row]:
    if not user_ids:
        return []
    return await _rows(
        session,
        """
        SELECT u.id, u.name,
               (SELECT r.role FROM staff_role r
                 WHERE r.user_id = u.id AND r.outlet_id = :outlet AND r.active
                 ORDER BY r.role LIMIT 1) AS role
          FROM app_user u WHERE u.id = ANY(:ids)""",
        {"outlet": outlet_id, "ids": user_ids},
    )


async def menu_items(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    return await _rows(
        session,
        f"""
        SELECT mi.id, mi.name, c.id AS category_id,
               COALESCE(c.name, 'Uncategorised') AS category,
               count(DISTINCT l.order_id) FILTER (WHERE act) AS rounds,
               COALESCE(SUM(l.qty) FILTER (WHERE act), 0)::int AS units,
               COALESCE(SUM(l.line_total) FILTER (WHERE act), 0) AS value,
               COALESCE(SUM(l.qty) FILTER (WHERE NOT act), 0)::int AS dropped_units
          FROM (
            SELECT l.*, (l.status NOT IN {_GONE} AND o.status <> 'cancelled') AS act
              FROM order_line l JOIN tab_order o ON o.id = l.order_id
             WHERE o.outlet_id = :outlet AND o.placed_at >= :lo AND o.placed_at < :hi
          ) l
          JOIN menu_item mi ON mi.id = l.menu_item_id
          LEFT JOIN menu_category c ON c.id = mi.category_id
         GROUP BY mi.id, mi.name, c.id, c.name""",
        _window(outlet_id, lo, hi, tz),
    )


async def menu_categories(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    return await _rows(
        session,
        f"""
        SELECT c.id, COALESCE(c.name, 'Uncategorised') AS name,
               count(DISTINCT l.order_id) AS rounds,
               COALESCE(SUM(l.qty), 0)::int AS units,
               COALESCE(SUM(l.line_total), 0) AS value
          FROM order_line l
          JOIN tab_order o ON o.id = l.order_id
          JOIN menu_item mi ON mi.id = l.menu_item_id
          LEFT JOIN menu_category c ON c.id = mi.category_id
         WHERE o.outlet_id = :outlet AND o.placed_at >= :lo AND o.placed_at < :hi
           AND o.status <> 'cancelled' AND l.status NOT IN {_GONE}
         GROUP BY c.id, c.name""",
        _window(outlet_id, lo, hi, tz),
    )


async def table_activity(
    session: AsyncSession, outlet_id: UUID, lo: datetime, hi: datetime, tz: str
) -> list[Row]:
    return await _rows(
        session,
        f"""
        WITH {_ORDERS}, per_table AS (
          SELECT tb.table_id, count(DISTINCT tb.id) AS visits,
                 count(*) FILTER (WHERE o.status <> 'cancelled' AND o.units > 0) AS rounds,
                 COALESCE(SUM(o.value) FILTER (WHERE o.status <> 'cancelled'), 0) AS value,
                 COALESCE(SUM(tb.guest_count) FILTER (WHERE o.rn = 1), 0) AS guests
            FROM (SELECT orders.*, row_number() OVER (PARTITION BY tab_id ORDER BY placed_at)
                         AS rn FROM orders) o
            JOIN tab tb ON tb.id = o.tab_id
           WHERE tb.table_id IS NOT NULL
           GROUP BY tb.table_id
        )
        SELECT d.id, d.label, d.zone, d.seats,
               COALESCE(p.visits, 0) AS visits, COALESCE(p.rounds, 0) AS rounds,
               COALESCE(p.value, 0) AS value, COALESCE(p.guests, 0)::int AS guests
          FROM dining_table d LEFT JOIN per_table p ON p.table_id = d.id
         WHERE d.outlet_id = :outlet AND d.active
         ORDER BY d.label""",
        _window(outlet_id, lo, hi, tz),
    )


async def order_list(
    session: AsyncSession,
    outlet_id: UUID,
    lo: datetime,
    hi: datetime,
    tz: str,
    expected_minutes: int,
    *,
    limit: int,
    cursor: tuple[datetime, UUID] | None = None,
    status: str | None = None,
    item_id: UUID | None = None,
    category_id: UUID | None = None,
    served_by: UUID | None = None,
    table_id: UUID | None = None,
    weekday: int | None = None,
    hour: int | None = None,
    day: date | None = None,
    delayed: bool = False,
) -> list[Row]:
    """The rounds behind a number, newest first, keyset-paged. Every filter is a fixed SQL
    fragment with a bound value; nothing from the request is spliced into the statement."""
    where = ["o.outlet_id = :outlet", "o.placed_at >= :lo", "o.placed_at < :hi"]
    params: dict[str, Any] = {
        "outlet": outlet_id,
        "lo": lo,
        "hi": hi,
        "tz": tz,
        "expected_s": expected_minutes * 60,
        "limit": limit + 1,
    }
    if cursor is not None:
        where.append("(o.placed_at, o.id) < (:c_at, :c_id)")
        params["c_at"], params["c_id"] = cursor
    if status is not None:
        where.append("o.status = :status")
        params["status"] = status
    if item_id is not None:
        where.append(
            f"EXISTS (SELECT 1 FROM order_line x WHERE x.order_id = o.id "
            f"AND x.menu_item_id = :item AND x.status NOT IN {_GONE})"
        )
        params["item"] = item_id
    if category_id is not None:
        where.append(
            f"EXISTS (SELECT 1 FROM order_line x JOIN menu_item m ON m.id = x.menu_item_id "
            f"WHERE x.order_id = o.id AND m.category_id = :category AND x.status NOT IN {_GONE})"
        )
        params["category"] = category_id
    if served_by is not None:
        where.append(
            "EXISTS (SELECT 1 FROM order_line x WHERE x.order_id = o.id AND x.served_by = :by)"
        )
        params["by"] = served_by
    if table_id is not None:
        where.append("tb.table_id = :table")
        params["table"] = table_id
    if weekday is not None:
        where.append("CAST(extract(isodow FROM o.placed_at AT TIME ZONE :tz) AS int) = :weekday")
        params["weekday"] = weekday
    if hour is not None:
        where.append("CAST(extract(hour FROM o.placed_at AT TIME ZONE :tz) AS int) = :hour")
        params["hour"] = hour
    if day is not None:
        where.append("(o.placed_at AT TIME ZONE :tz)::date = :day")
        params["day"] = day
    if delayed:
        where.append(
            "EXISTS (SELECT 1 FROM ticket t WHERE t.order_id = o.id AND t.status <> 'cancelled' "
            "AND t.ready_at >= t.started_at "
            "AND extract(epoch FROM t.ready_at - t.started_at) > :expected_s)"
        )
    return await _rows(
        session,
        f"""
        SELECT o.id, o.tab_id, o.seq_no, o.status, o.source, o.placed_at, d.label AS table_label,
               (SELECT COALESCE(SUM(x.line_total), 0) FROM order_line x
                 WHERE x.order_id = o.id AND x.status NOT IN {_GONE}) AS value,
               (SELECT string_agg(x.qty || ' × ' || x.item_name_snapshot, ', '
                                  ORDER BY x.position)
                  FROM order_line x WHERE x.order_id = o.id AND x.status NOT IN {_GONE}) AS items,
               (SELECT max(extract(epoch FROM t.ready_at - t.started_at)) FROM ticket t
                 WHERE t.order_id = o.id AND t.status <> 'cancelled'
                   AND t.ready_at >= t.started_at) AS prep,
               (SELECT string_agg(DISTINCT COALESCE(u.name, 'Unnamed'), ', ')
                  FROM order_line x JOIN app_user u ON u.id = x.served_by
                 WHERE x.order_id = o.id) AS served_by
          FROM tab_order o
          JOIN tab tb ON tb.id = o.tab_id
          LEFT JOIN dining_table d ON d.id = tb.table_id
         WHERE {" AND ".join(where)}
         ORDER BY o.placed_at DESC, o.id DESC
         LIMIT :limit""",
        params,
    )
