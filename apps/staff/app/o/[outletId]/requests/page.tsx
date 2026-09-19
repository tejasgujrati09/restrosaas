"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ErrorBanner } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import { ageClass, minutesSince, timeOf } from "@/lib/floor";
import type { RequestRow } from "@/lib/types";
import { useNow } from "@/lib/use-now";

const LABELS: Record<string, string> = { water: "Water", waiter: "Waiter", bill: "Bill", other: "Other" };

/** Water, waiter and bill requests, oldest first. */
export default function RequestsPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}/staff`;
  const feed = useResource<RequestRow[]>(`${base}/service-requests`, 15_000, true);
  const action = useAction();
  const now = useNow();

  if (!feed.data) return <ErrorBanner message={feed.error} />;
  return (
    <>
      <h1>Requests</h1>
      <ErrorBanner message={action.error ?? feed.error} />
      {feed.data.length === 0 ? <p>Nothing waiting.</p> : null}
      {feed.data.map((r) => {
        const waited = minutesSince(r.created_at, now);
        return (
          <section key={r.id} className={`card ticket ${r.type === "bill" ? ageClass(Math.max(waited, 0) * 3) : ageClass(waited)}`}>
            <h3>
              {LABELS[r.type] ?? r.type} · Table {r.table_label ?? "?"}
            </h3>
            <p className="muted">
              {timeOf(r.created_at)} · waiting {waited} min
            </p>
            <div className="inline">
              <Link className="button secondary" href={`/o/${outletId}/floor/${r.tab_id}`}>Open table</Link>
              <button
                type="button"
                disabled={action.busy}
                onClick={async () => {
                  if (await action.run(() => api(`${base}/service-requests/${r.id}/resolve`, { method: "POST" }))) feed.reload();
                }}
              >
                Done
              </button>
            </div>
          </section>
        );
      })}
    </>
  );
}
