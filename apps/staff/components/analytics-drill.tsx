"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAction, useResource } from "@/components/hooks";
import { Badge, Card, EmptyState, ErrorBanner, formatInr, Skeleton } from "@restosaas/ui";
import type { Drill } from "@/components/analytics-panels";
import { api } from "@/lib/api";
import { formatDuration, localTime, STATUS_LABELS } from "@/lib/analytics";
import type { AnalyticsOrders } from "@/lib/types";

type Row = AnalyticsOrders["rows"][number];

/** The rounds behind a number, newest first, fifty at a time. Each links to its tab. */
export function DrillPanel({ outletId, query, drill, onClose }: { outletId: string; query: string; drill: Drill; onClose: () => void }) {
  const params = new URLSearchParams(query);
  for (const [k, v] of Object.entries(drill.params)) params.set(k, v);
  const path = `/v1/outlets/${outletId}/analytics/orders`;
  // The first page loads like any resource; later pages are added by "Show more".
  const first = useResource<AnalyticsOrders>(`${path}?${params}`);
  const [more, setMore] = useState<{ rows: Row[]; cursor: string | null } | null>(null);
  const action = useAction();
  const heading = useRef<HTMLHeadingElement>(null);
  // The parent keys this panel by the number being explored, so each one starts fresh.
  useEffect(() => heading.current?.focus(), []);

  const rows = [...(first.data?.rows ?? []), ...(more?.rows ?? [])];
  const cursor = more ? more.cursor : (first.data?.next_cursor ?? null);
  const zone = first.data?.range.timezone ?? "UTC";
  const loading = first.loading || action.busy;
  const error = first.error ?? action.error;

  function showMore() {
    if (!cursor) return;
    const next = new URLSearchParams(params);
    next.set("cursor", cursor);
    void action.run(async () => {
      const page = await api<AnalyticsOrders>(`${path}?${next}`);
      setMore({ rows: [...(more?.rows ?? []), ...page.rows], cursor: page.next_cursor ?? null });
    });
  }

  return (
    <Card>
      <div className="section-head">
        <div>
          <h2 tabIndex={-1} ref={heading}>
            Rounds for {drill.label}
          </h2>
          <p className="hint">Newest first. Open a tab to see its full event log.</p>
        </div>
        <button type="button" className="secondary" onClick={onClose}>
          Close list
        </button>
      </div>
      <ErrorBanner message={error} />
      {first.loading ? <Skeleton what="rounds" lines={4} /> : null}
      {!first.loading && !error && rows.length === 0 ? (
        <EmptyState title="No rounds match">Nothing in this range matches that number.</EmptyState>
      ) : null}
      {rows.length > 0 ? (
        <table className="stacked">
          <thead>
            <tr>
              <th>Placed</th>
              <th>Table</th>
              <th>Items</th>
              <th>Status</th>
              <th>Order value</th>
              <th>Prep</th>
              <th>Served by</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td data-label="Placed">{localTime(r.placed_at, zone)}</td>
                <td data-label="Table">
                  {r.table_label ?? "–"} · round {r.seq_no}
                </td>
                <td data-label="Items">{r.items ?? "Nothing left on it"}</td>
                <td data-label="Status">
                  <Badge tone={r.status === "cancelled" ? "danger" : r.status === "served" ? "ok" : "info"}>{STATUS_LABELS[r.status] ?? r.status}</Badge>
                </td>
                <td data-label="Order value">{formatInr(r.order_value_paise)}</td>
                <td data-label="Prep">
                  {r.prep_seconds !== null ? formatDuration(r.prep_seconds) : "–"} {r.delayed ? <Badge tone="warn">Delayed</Badge> : null}
                </td>
                <td data-label="Served by">{r.served_by ?? "–"}</td>
                <td>
                  <Link className="button tertiary" href={`/o/${outletId}/floor/${r.tab_id}`}>
                    Open tab
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {cursor ? (
        <button type="button" className="secondary" disabled={loading} onClick={showMore}>
          {loading ? "Loading…" : "Show more"}
        </button>
      ) : null}
    </Card>
  );
}
