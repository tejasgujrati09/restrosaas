"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo } from "react";
import { formatInr } from "@restosaas/ui";
import { ErrorBanner } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import { STATE_LABELS, timeOf } from "@/lib/floor";
import { rolesAt } from "@/lib/session";
import type { Alert, OpenTab, TableCard, TableMap } from "@/lib/types";
import { useToken } from "@/lib/use-token";

export default function FloorPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const router = useRouter();
  const base = `/v1/outlets/${outletId}/staff`;
  const token = useToken();
  const isManager = useMemo(() => rolesAt(token, outletId).some((r) => r === "manager" || r === "owner"), [token, outletId]);
  const map = useResource<TableMap>(`${base}/table-map`, 15_000, true);
  const alerts = useResource<Alert[]>(isManager ? `${base}/alerts` : null, 30_000, true);
  const action = useAction();

  if (!map.data) return <ErrorBanner message={map.error} />;
  const zones = new Map<string, TableCard[]>();
  for (const t of map.data.tables) zones.set(t.zone, [...(zones.get(t.zone) ?? []), t]);

  async function open(table: TableCard) {
    const result = await action.call(() => api<OpenTab>(`${base}/tables/${table.id}/tab`, { method: "POST", body: {} }));
    if (result) router.push(`/o/${outletId}/floor/${result.tab_id}`);
  }

  return (
    <>
      <h1>Floor</h1>
      <ErrorBanner message={action.error ?? map.error} />
      {map.data.unassigned ? (
        <p className="card">You have no tables yet. Ask a manager to assign you some.</p>
      ) : null}
      {alerts.data && alerts.data.length > 0 ? (
        <section className="card" aria-label="Alerts">
          <h2>Needs a manager</h2>
          <ul>
            {alerts.data.map((a) => (
              <li key={a.line_id}>
                <Link href={`/o/${outletId}/floor/${a.tab_id}`}>
                  Table {a.table_label ?? "?"}
                </Link>{" "}
                {a.kind === "line_disputed" ? "says" : "hasn't answered about"} <strong>{a.item}</strong> ({formatInr(a.line_total_paise)}
                {a.staff_name ? `, added by ${a.staff_name}` : ""}) {a.kind === "line_disputed" ? "isn't theirs" : ""} · since {timeOf(a.since)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {[...zones.entries()].map(([zone, tables]) => (
        <section key={zone} aria-label={zone}>
          <h2>{zone}</h2>
          <div className="tiles">
            {tables.map((t) => {
              const body = (
                <>
                  <span className="tile-name">{t.label}</span>
                  <span>{STATE_LABELS[t.state] ?? t.state}</span>
                  {t.tab_id ? <span className="muted">{formatInr(t.estimated_total_paise)}</span> : <span className="muted">Tap to open a tab</span>}
                  <span className="pills">
                    {t.awaiting_confirm ? <span className="pill hot">Confirm table</span> : null}
                    {t.pending_rounds > 0 ? <span className="pill">{t.pending_rounds} in progress</span> : null}
                    {t.ready_rounds > 0 ? <span className="pill ready">{t.ready_rounds} ready</span> : null}
                    {t.open_requests.map((r) => (
                      <span key={r} className="pill hot">{r}</span>
                    ))}
                    {t.awaiting_ack > 0 ? <span className="pill">Awaiting guest OK</span> : null}
                    {t.disputes > 0 ? <span className="pill hot">Disputed</span> : null}
                  </span>
                </>
              );
              return t.tab_id ? (
                <Link key={t.id} href={`/o/${outletId}/floor/${t.tab_id}`} className={`tile state-${t.state}`}>
                  {body}
                </Link>
              ) : (
                <button key={t.id} type="button" className={`tile state-${t.state}`} disabled={action.busy || !t.active} onClick={() => open(t)}>
                  {body}
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </>
  );
}
