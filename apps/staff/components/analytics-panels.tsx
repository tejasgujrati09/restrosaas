"use client";

import { useState, type FormEvent } from "react";
import { Badge, Card, EmptyState, ErrorBanner, Field, formatInr, Notice, Skeleton } from "@restosaas/ui";
import { Bars, Heatmap, KpiCard, LowSample, SectionHead, type BarItem } from "@/components/analytics-parts";
import { useAction, useResource } from "@/components/hooks";
import { api, openBlob } from "@/lib/api";
import {
  formatDuration,
  hourLabel,
  QUADRANT_LABELS,
  rangeText,
  shortDate,
  STATUS_LABELS,
  windowsLabel,
} from "@/lib/analytics";
import type {
  AnalyticsKitchen,
  AnalyticsMenu,
  AnalyticsOverview,
  AnalyticsStaff,
  AnalyticsTables,
} from "@/lib/types";

export type Drill = { label: string; params: Record<string, string> };

export type PanelProps = {
  outletId: string;
  /** Query string for the chosen range, e.g. `range=today`. */
  query: string;
  onDrill: (drill: Drill) => void;
};

const paise = (n: number) => formatInr(n);

function PanelState<T>({
  resource,
  what,
  children,
}: {
  resource: { data: T | null; error: string | null; reload: () => void };
  what: string;
  children: (data: T) => React.ReactNode;
}) {
  if (resource.error && !resource.data) {
    return (
      <Card>
        <ErrorBanner message={resource.error} />
        <button type="button" className="secondary" onClick={resource.reload}>
          Try again
        </button>
      </Card>
    );
  }
  if (!resource.data) {
    return (
      <Card>
        <Skeleton what={what} lines={4} />
      </Card>
    );
  }
  return <>{children(resource.data)}</>;
}

function ViewOrders({ drill, onDrill }: { drill: Drill; onDrill: (d: Drill) => void }) {
  return (
    <button type="button" className="tertiary" onClick={() => onDrill(drill)}>
      View orders<span className="visually-hidden"> for {drill.label}</span>
    </button>
  );
}

function ExportButton({ outletId, kind, query }: { outletId: string; kind: string; query: string }) {
  const action = useAction();
  return (
    <>
      <button
        type="button"
        className="secondary"
        disabled={action.busy}
        onClick={() =>
          action.run(() => openBlob(`/v1/outlets/${outletId}/analytics/export/${kind}?${query}`, `${kind}.csv`))
        }
      >
        {action.busy ? "Preparing…" : "Download CSV"}
      </button>
      <ErrorBanner message={action.error} />
    </>
  );
}

// ------------------------------------------------------------------ overview

const TREND_METRICS = [
  { key: "value", label: "Order value" },
  { key: "orders", label: "Rounds" },
  { key: "prep", label: "Average prep time" },
] as const;

const HOUR_METRICS = [
  { key: "orders", label: "Rounds placed" },
  { key: "tickets", label: "Kitchen tickets" },
  { key: "served", label: "Items served" },
] as const;

export function OverviewPanel({ outletId, query, onDrill }: PanelProps) {
  const res = useResource<AnalyticsOverview>(`/v1/outlets/${outletId}/analytics/overview?${query}`);
  const [trendKey, setTrendKey] = useState<(typeof TREND_METRICS)[number]["key"]>("value");
  const [hourKey, setHourKey] = useState<(typeof HOUR_METRICS)[number]["key"]>("orders");
  return (
    <PanelState resource={res} what="overview">
      {(o) => {
        const k = o.kpis;
        const trend: BarItem[] = o.trend.map((p) => {
          const value = trendKey === "value" ? p.order_value_paise : trendKey === "orders" ? p.orders : p.avg_prep_seconds;
          const text =
            trendKey === "value"
              ? paise(p.order_value_paise)
              : trendKey === "orders"
                ? `${p.orders} rounds`
                : p.avg_prep_seconds === null
                  ? "No timed tickets"
                  : `${formatDuration(p.avg_prep_seconds)} (${p.prep_n} tickets)`;
          const label = o.range.bucket === "month" ? (shortDate(p.bucket).split(" ")[1] ?? "") : shortDate(p.bucket);
          return { key: p.bucket, label, value: value ?? null, text };
        });
        const byHour: BarItem[] = o.peak.by_hour.map((h) => {
          const value = hourKey === "orders" ? h.orders : hourKey === "tickets" ? h.tickets : h.lines_served;
          return { key: String(h.hour), label: hourLabel(h.hour).replace(" ", "").toLowerCase(), value, text: String(value) };
        });
        const mixTotal = o.status_mix.reduce((n, s) => n + s.n, 0);
        const noData = k.orders.value === 0 && o.cancellations.rounds === 0;
        return (
          <>
            <Notice tone="info">
              Figures here are order values at the price locked when ordered, before tax, discounts and service charge.
              Revenue, bills, refunds and payment methods will appear here once billing is added.
            </Notice>
            {noData ? (
              <EmptyState title="No orders in this range">Pick a wider range, or check back after the next service.</EmptyState>
            ) : null}
            <div className="kpi-grid">
              <KpiCard title="Rounds" kpi={k.orders} note={o.pending_orders ? `${o.pending_orders} still in progress` : undefined} />
              <KpiCard title="Order value" kpi={k.order_value} />
              <KpiCard title="Average order value" kpi={k.avg_order_value} />
              <KpiCard title="Items per round" kpi={k.items_per_order} />
              <KpiCard title="Average prep time" kpi={k.avg_prep} />
              <KpiCard title="Ready to served" kpi={k.avg_ready_to_served} />
              <KpiCard title="Cancellation rate" kpi={k.cancellation_rate} />
            </div>
            <p className="hint">
              Compared with {rangeText(o.range.previous_start, o.range.previous_end)}. Times are in {o.range.timezone}.
            </p>

            <Card>
              <SectionHead
                title="Trend"
                hint={`By ${o.range.bucket}. What are we selling, and is it going up or down?`}
                actions={
                  <div className="seg" role="group" aria-label="Trend measure">
                    {TREND_METRICS.map((m) => (
                      <button key={m.key} type="button" aria-pressed={trendKey === m.key} onClick={() => setTrendKey(m.key)}>
                        {m.label}
                      </button>
                    ))}
                  </div>
                }
              />
              <Bars
                items={trend}
                name={o.range.bucket === "day" ? "Day" : o.range.bucket === "week" ? "Week starting" : "Month"}
                unitLabel={TREND_METRICS.find((m) => m.key === trendKey)!.label}
                labelEvery={Math.max(1, Math.ceil(trend.length / 6))}
              />
              {o.range.bucket === "day" ? (
                <details className="chart-table">
                  <summary>Open the rounds behind a day</summary>
                  <ul className="list">
                    {o.trend
                      .filter((p) => p.orders > 0 || p.cancelled > 0)
                      .map((p) => (
                        <li key={p.bucket}>
                          <span>
                            {shortDate(p.bucket)}: {p.orders} rounds, {paise(p.order_value_paise)}
                          </span>
                          <ViewOrders drill={{ label: shortDate(p.bucket), params: { day: p.bucket } }} onDrill={onDrill} />
                        </li>
                      ))}
                  </ul>
                </details>
              ) : null}
            </Card>

            <Card>
              <SectionHead
                title="Busiest hours"
                hint={
                  o.peak.windows.length
                    ? `Peak: ${windowsLabel(o.peak.windows)} (hours within a quarter of the busiest). When do we need the most capacity?`
                    : "When do we need the most capacity?"
                }
                actions={
                  <div className="seg" role="group" aria-label="Hour measure">
                    {HOUR_METRICS.map((m) => (
                      <button key={m.key} type="button" aria-pressed={hourKey === m.key} onClick={() => setHourKey(m.key)}>
                        {m.label}
                      </button>
                    ))}
                  </div>
                }
              />
              <Bars items={byHour} name="Hour" unitLabel={HOUR_METRICS.find((m) => m.key === hourKey)!.label} labelEvery={3} />
              <h3>Weekday and hour</h3>
              <Heatmap grid={o.peak.heatmap} />
              <details className="chart-table">
                <summary>Open the rounds behind an hour</summary>
                <ul className="list">
                  {o.peak.by_hour
                    .filter((h) => h.orders > 0)
                    .map((h) => (
                      <li key={h.hour}>
                        <span>
                          {hourLabel(h.hour)}: {h.orders} rounds, {paise(h.order_value_paise)}
                        </span>
                        <ViewOrders drill={{ label: hourLabel(h.hour), params: { hour: String(h.hour) } }} onDrill={onDrill} />
                      </li>
                    ))}
                </ul>
              </details>
            </Card>

            <div className="two-col">
              <Card>
                <SectionHead title="Round status" hint="Where rounds stand right now, for rounds placed in this range." />
                {o.status_mix.length === 0 ? (
                  <p className="hint">No rounds in this range.</p>
                ) : (
                  <ul className="list">
                    {o.status_mix.map((s) => (
                      <li key={s.status}>
                        <span>
                          <Badge tone={s.status === "cancelled" ? "danger" : s.status === "served" ? "ok" : "info"}>
                            {STATUS_LABELS[s.status] ?? s.status}
                          </Badge>{" "}
                          {s.n} ({Math.round((s.n / mixTotal) * 100)}%)
                        </span>
                        <ViewOrders drill={{ label: STATUS_LABELS[s.status] ?? s.status, params: { status: s.status } }} onDrill={onDrill} />
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card>
                <SectionHead title="Cancellations" />
                <p>
                  <strong>{o.cancellations.rounds}</strong> cancelled rounds
                  {o.cancellations.rate_pct !== null ? ` (${o.cancellations.rate_pct}% of rounds placed)` : ""}, worth{" "}
                  {paise(o.cancellations.value_paise)}.
                </p>
                {o.cancellations.items.length ? (
                  <ul className="list">
                    {o.cancellations.items.map((i) => (
                      <li key={i.name}>
                        <span>{i.name}</span>
                        <span>
                          {i.units} cancelled, {paise(i.value_paise)}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                <p className="hint">{o.cancellations.note}</p>
              </Card>
            </div>
            {o.can_export ? (
              <Card>
                <SectionHead title="Export" hint="Every round in this range, one row each." actions={<ExportButton outletId={outletId} kind="orders" query={query} />} />
              </Card>
            ) : null}
          </>
        );
      }}
    </PanelState>
  );
}

// ------------------------------------------------------------------ kitchen

function ExpectedPrep({ outletId, minutes, onSaved }: { outletId: string; minutes: number; onSaved: () => void }) {
  const [value, setValue] = useState(String(minutes));
  const [problem, setProblem] = useState<string | null>(null);
  const action = useAction();
  async function save(event: FormEvent) {
    event.preventDefault();
    const n = Number(value);
    if (!Number.isInteger(n) || n < 1 || n > 240) {
      setProblem("Enter a whole number of minutes between 1 and 240.");
      return;
    }
    setProblem(null);
    if (await action.run(() => api(`/v1/outlets/${outletId}/analytics/expected-prep`, { method: "PUT", body: { minutes: n } }))) onSaved();
  }
  return (
    <form onSubmit={save} className="row">
      <Field label="Expected prep time (minutes)" size="short" hint="A ticket that takes longer than this counts as delayed." error={problem}>
        <input inputMode="numeric" value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
      <button type="submit" disabled={action.busy || Number(value) === minutes}>
        {action.busy ? "Saving…" : "Save"}
      </button>
      <ErrorBanner message={action.error} />
    </form>
  );
}

export function KitchenPanel({ outletId, query, onDrill }: PanelProps) {
  const res = useResource<AnalyticsKitchen>(`/v1/outlets/${outletId}/analytics/kitchen?${query}`, 60_000);
  return (
    <PanelState resource={res} what="kitchen figures">
      {(k) => {
        const c = k.coverage;
        const trend: BarItem[] = k.trend.map((p) => ({
          key: p.key,
          label: shortDate(p.key),
          value: p.avg_prep_seconds ?? null,
          text: p.avg_prep_seconds === null ? "No timed tickets" : `${formatDuration(p.avg_prep_seconds)} (${p.n} tickets)`,
        }));
        const byHour: BarItem[] = k.by_hour.map((p, h) => ({
          key: p.key,
          label: hourLabel(h).replace(" ", "").toLowerCase(),
          value: p.avg_prep_seconds ?? null,
          text: p.avg_prep_seconds === null ? "No timed tickets" : `${formatDuration(p.avg_prep_seconds)} (${p.n} tickets)`,
        }));
        const live = k.live;
        return (
          <>
            <Card>
              <SectionHead title="Right now" hint="Live, whatever the date range. Delayed means longer than the expected prep time." actions={<button type="button" className="secondary" onClick={res.reload}>Refresh</button>} />
              <div className="kpi-grid">
                <article className="kpi">
                  <h3>Waiting for the kitchen</h3>
                  <p className="kpi-value">{live.waiting_for_kitchen.n}</p>
                  <p className="kpi-basis">
                    {live.waiting_for_kitchen.longest_seconds !== null ? `Longest wait ${formatDuration(live.waiting_for_kitchen.longest_seconds)}` : "Nothing waiting"}
                  </p>
                  {live.waiting_for_kitchen.over_expected ? <Badge tone="warn">{live.waiting_for_kitchen.over_expected} over {k.expected_prep_minutes} min</Badge> : null}
                </article>
                <article className="kpi">
                  <h3>Being prepared</h3>
                  <p className="kpi-value">{live.preparing.n}</p>
                  <p className="kpi-basis">{live.preparing.longest_seconds !== null ? `Longest ${formatDuration(live.preparing.longest_seconds)}` : "Nothing cooking"}</p>
                  {live.preparing.over_expected ? <Badge tone="warn">{live.preparing.over_expected} over {k.expected_prep_minutes} min</Badge> : null}
                </article>
                <article className="kpi">
                  <h3>Ready, not yet served</h3>
                  <p className="kpi-value">{live.ready_awaiting_serve.n}</p>
                  <p className="kpi-basis">{live.ready_awaiting_serve.longest_seconds !== null ? `Longest ${formatDuration(live.ready_awaiting_serve.longest_seconds)}` : "Nothing waiting"}</p>
                  <p className="kpi-basis">Counted, not judged: no target is set for serving.</p>
                </article>
              </div>
            </Card>

            <div className="kpi-grid">
              <KpiCard title="Average prep time" kpi={k.kpis.avg_prep} />
              <KpiCard title="Average wait to start" kpi={k.kpis.avg_wait} />
              <KpiCard title="Placed to ready" kpi={k.kpis.avg_to_ready} />
              <KpiCard title="Ready to served" kpi={k.kpis.avg_ready_to_served} />
              <KpiCard title={`Over ${k.expected_prep_minutes} minutes`} kpi={k.kpis.over_expected} />
            </div>
            <p className="hint">
              Timings use {c.used} of {c.total} tickets. Left out: {c.cancelled} cancelled, {c.unfinished} not yet started or ready, {c.invalid} with timestamps out of order.
            </p>
            <div className="row">
              <button type="button" className="secondary" onClick={() => onDrill({ label: `prep over ${k.expected_prep_minutes} min`, params: { delayed: "true" } })}>
                View orders that took too long
              </button>
            </div>

            {k.can_edit_expected_prep ? (
              <Card title="Expected prep time">
                <ExpectedPrep outletId={outletId} minutes={k.expected_prep_minutes} onSaved={res.reload} />
              </Card>
            ) : (
              <p className="hint">Expected prep time is {k.expected_prep_minutes} minutes. An owner or manager can change it.</p>
            )}

            <Card>
              <SectionHead title="Prep time by day" hint="Average time from start to ready." />
              <Bars items={trend} name={k.range.bucket === "day" ? "Day" : k.range.bucket === "week" ? "Week starting" : "Month"} unitLabel="Average prep" labelEvery={Math.max(1, Math.ceil(trend.length / 6))} />
            </Card>
            <Card>
              <SectionHead title="Prep time by hour" hint="Hour the round was placed." />
              <Bars items={byHour} name="Hour" unitLabel="Average prep" labelEvery={3} />
            </Card>

            <Card>
              <SectionHead title="By menu category" />
              {k.by_category.length === 0 ? (
                <EmptyState title="No timed tickets">Timings appear once the kitchen starts and marks tickets ready.</EmptyState>
              ) : (
                <table className="stacked">
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th>Average prep</th>
                      <th>Tickets</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {k.by_category.map((c2) => (
                      <tr key={c2.id ?? c2.name}>
                        <td data-label="Category">{c2.name}</td>
                        <td data-label="Average prep">{formatDuration(c2.avg_prep_seconds)}</td>
                        <td data-label="Tickets">
                          {c2.n} {c2.low_sample ? <LowSample /> : null}
                        </td>
                        <td>{c2.id ? <ViewOrders drill={{ label: c2.name, params: { category_id: c2.id } }} onDrill={onDrill} /> : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>

            <div className="two-col">
              <ItemTable title="Slowest items" rows={k.slowest} onDrill={onDrill} />
              <ItemTable title="Fastest items" rows={k.fastest} onDrill={onDrill} />
            </div>
            <p className="hint">
              {k.note}
              {k.items_hidden_low_sample ? ` ${k.items_hidden_low_sample} items have too few tickets to rank.` : ""}
            </p>
          </>
        );
      }}
    </PanelState>
  );
}

function ItemTable({ title, rows, onDrill }: { title: string; rows: AnalyticsKitchen["slowest"]; onDrill: (d: Drill) => void }) {
  return (
    <Card title={title}>
      {rows.length === 0 ? (
        <p className="hint">Not enough tickets yet to rank items.</p>
      ) : (
        <table className="stacked">
          <thead>
            <tr>
              <th>Item</th>
              <th>Average prep</th>
              <th>Tickets</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id ?? r.name}>
                <td data-label="Item">
                  {r.name}
                  <br />
                  <span className="hint">{r.category}</span>
                </td>
                <td data-label="Average prep">{formatDuration(r.avg_prep_seconds)}</td>
                <td data-label="Tickets">{r.n}</td>
                <td>{r.id ? <ViewOrders drill={{ label: r.name, params: { item_id: r.id } }} onDrill={onDrill} /> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ staff

const STAFF_SORTS = [
  { key: "lines", label: "Most items served" },
  { key: "per_day", label: "Most items per active day" },
  { key: "fast", label: "Fastest ready to served" },
  { key: "tables", label: "Most tables" },
  { key: "value", label: "Highest order value served" },
] as const;

export function StaffPanel({ outletId, query, onDrill }: PanelProps) {
  const res = useResource<AnalyticsStaff>(`/v1/outlets/${outletId}/analytics/staff?${query}`);
  const [sort, setSort] = useState<(typeof STAFF_SORTS)[number]["key"]>("lines");
  return (
    <PanelState resource={res} what="staff figures">
      {(s) => {
        const rows = [...s.rows].sort((a, b) => {
          switch (sort) {
            case "per_day":
              return (b.lines_per_active_day ?? 0) - (a.lines_per_active_day ?? 0);
            case "fast":
              // People with no timed serves go last: no data is not "fastest".
              return (a.avg_ready_to_served_seconds ?? Infinity) - (b.avg_ready_to_served_seconds ?? Infinity);
            case "tables":
              return b.tables_served - a.tables_served;
            case "value":
              return b.order_value_served_paise - a.order_value_served_paise;
            default:
              return b.lines_served - a.lines_served;
          }
        });
        const hourly: BarItem[] = s.by_hour.map((h) => ({
          key: String(h.hour),
          label: hourLabel(h.hour).replace(" ", "").toLowerCase(),
          value: h.lines_served,
          text: `${h.lines_served} items, ${h.staff_active} staff${h.lines_per_staff !== null ? `, ${h.lines_per_staff} each` : ""}`,
        }));
        return (
          <>
            <Card>
              <SectionHead
                title="Compare staff"
                hint="Plain measures, no score. A bigger number is not automatically better: compare items per active day and time to serve, not totals alone."
                actions={
                  <Field label="Sort by">
                    <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
                      {STAFF_SORTS.map((o) => (
                        <option key={o.key} value={o.key}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                }
              />
              {rows.length === 0 ? (
                <EmptyState title="No serving recorded in this range">Items served show here once waiters mark items served.</EmptyState>
              ) : (
                <table className="stacked">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Items served</th>
                      <th>Rounds</th>
                      <th>Tables</th>
                      <th>Per active day</th>
                      <th>Ready to served</th>
                      <th>Order value served</th>
                      <th>Rounds entered</th>
                      <th>Busiest hour</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.user_id}>
                        <td data-label="Name">
                          {r.name}
                          {r.role ? <span className="hint"> · {r.role}</span> : null}
                        </td>
                        <td data-label="Items served">{r.lines_served}</td>
                        <td data-label="Rounds">{r.rounds_served}</td>
                        <td data-label="Tables">{r.tables_served}</td>
                        <td data-label="Per active day">{r.lines_per_active_day ?? "–"}</td>
                        <td data-label="Ready to served">
                          {r.avg_ready_to_served_seconds !== null ? `${formatDuration(r.avg_ready_to_served_seconds)} (${r.ready_to_served_n} items)` : "No timed items"}
                        </td>
                        <td data-label="Order value served">{paise(r.order_value_served_paise)}</td>
                        <td data-label="Rounds entered">{r.rounds_entered}</td>
                        <td data-label="Busiest hour">{r.peak_hour !== null ? `${hourLabel(r.peak_hour)} (${r.peak_hour_lines})` : "–"}</td>
                        <td>{r.lines_served > 0 ? <ViewOrders drill={{ label: r.name, params: { served_by: r.user_id } }} onDrill={onDrill} /> : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
            <Card>
              <SectionHead title="Workload by hour" hint="Items served each hour, and how many staff served them. Are we understaffed at any hour?" />
              <Bars items={hourly} name="Hour" unitLabel="Items served" labelEvery={3} />
            </Card>
            <ul className="list notes">
              {s.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
            {s.can_export ? (
              <Card>
                <SectionHead title="Export" actions={<ExportButton outletId={outletId} kind="staff" query={query} />} />
              </Card>
            ) : null}
          </>
        );
      }}
    </PanelState>
  );
}

// ------------------------------------------------------------------ menu

export function MenuPanel({ outletId, query, onDrill }: PanelProps) {
  const res = useResource<AnalyticsMenu>(`/v1/outlets/${outletId}/analytics/menu?${query}`);
  const [sort, setSort] = useState<"units" | "value">("value");
  return (
    <PanelState resource={res} what="menu figures">
      {(m) => {
        const items = [...m.items].sort((a, b) => (sort === "units" ? b.units - a.units : b.order_value_paise - a.order_value_paise));
        return (
          <>
            {m.items.length === 0 ? (
              <EmptyState title="No items ordered in this range">Pick a wider range to see what sells.</EmptyState>
            ) : (
              <Card>
                <SectionHead
                  title="Items"
                  hint={`${m.total_units} items ordered, ${paise(m.total_order_value_paise)} order value. Most ordered and highest value are different lists.`}
                  actions={
                    <Field label="Rank by">
                      <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
                        <option value="value">Highest order value</option>
                        <option value="units">Most ordered (units)</option>
                      </select>
                    </Field>
                  }
                />
                <table className="stacked">
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th>Units</th>
                      <th>Rounds</th>
                      <th>Order value</th>
                      <th>Share</th>
                      <th>Avg price</th>
                      <th>Cancelled</th>
                      <th>Avg prep</th>
                      <th>Position</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((i) => (
                      <tr key={i.id}>
                        <td data-label="Item">
                          {i.name}
                          <br />
                          <span className="hint">{i.category}</span>
                        </td>
                        <td data-label="Units">{i.units}</td>
                        <td data-label="Rounds">{i.rounds}</td>
                        <td data-label="Order value">{paise(i.order_value_paise)}</td>
                        <td data-label="Share">{i.share_pct !== null ? `${i.share_pct}%` : "–"}</td>
                        <td data-label="Avg price">{i.avg_price_paise !== null ? paise(i.avg_price_paise) : "–"}</td>
                        <td data-label="Cancelled">{i.dropped_rate_pct !== null ? `${i.dropped_rate_pct}% (${i.dropped_units})` : "–"}</td>
                        <td data-label="Avg prep">{i.avg_prep_seconds !== null ? `${formatDuration(i.avg_prep_seconds)} (${i.prep_n})` : "–"}</td>
                        <td data-label="Position">{i.units > 0 ? QUADRANT_LABELS[i.quadrant] : "–"}</td>
                        <td>
                          <ViewOrders drill={{ label: i.name, params: { item_id: i.id } }} onDrill={onDrill} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {m.notes.map((n) => (
                  <p key={n} className="hint">
                    {n}
                  </p>
                ))}
              </Card>
            )}
            {m.categories.length ? (
              <Card title="Categories">
                <table className="stacked">
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th>Rounds</th>
                      <th>Units</th>
                      <th>Order value</th>
                      <th>Share</th>
                      <th>Avg per round</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {m.categories.map((c) => (
                      <tr key={c.id ?? c.name}>
                        <td data-label="Category">{c.name}</td>
                        <td data-label="Rounds">{c.rounds}</td>
                        <td data-label="Units">{c.units}</td>
                        <td data-label="Order value">{paise(c.order_value_paise)}</td>
                        <td data-label="Share">{c.share_pct !== null ? `${c.share_pct}%` : "–"}</td>
                        <td data-label="Avg per round">{c.avg_order_value_paise !== null ? paise(c.avg_order_value_paise) : "–"}</td>
                        <td>{c.id ? <ViewOrders drill={{ label: c.name, params: { category_id: c.id } }} onDrill={onDrill} /> : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            ) : null}
            {m.can_export ? (
              <Card>
                <SectionHead title="Export" actions={<ExportButton outletId={outletId} kind="menu" query={query} />} />
              </Card>
            ) : null}
          </>
        );
      }}
    </PanelState>
  );
}

// ------------------------------------------------------------------ tables

export function TablesPanel({ outletId, query, onDrill }: PanelProps) {
  const res = useResource<AnalyticsTables>(`/v1/outlets/${outletId}/analytics/tables?${query}`);
  return (
    <PanelState resource={res} what="table figures">
      {(t) => (
        <>
          <Card>
            <SectionHead title="Tables" hint="Order value at locked prices, highest first." />
            {t.rows.length === 0 ? (
              <EmptyState title="No tables yet">
                Add tables under Tables & QR to see them here.
              </EmptyState>
            ) : (
              <table className="stacked">
                <thead>
                  <tr>
                    <th>Table</th>
                    <th>Zone</th>
                    <th>Visits</th>
                    <th>Rounds</th>
                    <th>Order value</th>
                    <th>Avg per round</th>
                    <th>Guests</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {t.rows.map((r) => (
                    <tr key={r.id}>
                      <td data-label="Table">{r.label}</td>
                      <td data-label="Zone">{r.zone}</td>
                      <td data-label="Visits">{r.visits}</td>
                      <td data-label="Rounds">{r.rounds}</td>
                      <td data-label="Order value">{paise(r.order_value_paise)}</td>
                      <td data-label="Avg per round">{r.avg_round_value_paise !== null ? paise(r.avg_round_value_paise) : "–"}</td>
                      <td data-label="Guests">{r.guests || "–"}</td>
                      <td>{r.rounds > 0 ? <ViewOrders drill={{ label: `table ${r.label}`, params: { table_id: r.id } }} onDrill={onDrill} /> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <ul className="list notes">
            {t.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </>
      )}
    </PanelState>
  );
}
