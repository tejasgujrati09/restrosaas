"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, EmptyState, formatInr, humanize, Icon, PageHeader, Skeleton } from "@restosaas/ui";
import { Card, ErrorBanner } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import { act } from "@/lib/offline";
import { lineStatus, statusTone, timeOf } from "@/lib/floor";
import type { Line, RequestRow, Round, StaffTab, TableMap } from "@/lib/types";

function source(line: Line): string {
  return line.placed_by === "staff" ? `${line.staff_name ?? "Staff"} (waiter)` : "Guest";
}

export default function TablePage() {
  const { outletId, tabId } = useParams<{ outletId: string; tabId: string }>();
  const router = useRouter();
  const base = `/v1/outlets/${outletId}`;
  const tab = useResource<StaffTab>(`${base}/staff/tabs/${tabId}`, 10_000, true);
  const requests = useResource<RequestRow[]>(`${base}/staff/service-requests`, 30_000, true);
  const map = useResource<TableMap>(`${base}/staff/table-map`, 30_000, true);
  const action = useAction();
  const [panel, setPanel] = useState<"transfer" | "merge" | null>(null);

  if (!tab.data) return tab.error ? <ErrorBanner message={tab.error} onRetry={tab.reload} /> : <Skeleton what="this table" lines={4} block />;
  const view = tab.data.tab;
  const mine = (requests.data ?? []).filter((r) => r.tab_id === tabId);
  const freeTables = (map.data?.tables ?? []).filter((t) => t.active && t.state === "empty");
  const otherTabs = (map.data?.tables ?? []).filter((t) => t.tab_id && t.tab_id !== tabId);
  const live = view.status === "open" || view.status === "bill_requested";

  async function run(fn: () => Promise<unknown>): Promise<boolean> {
    const done = await action.run(fn);
    tab.reload();
    map.reload();
    requests.reload();
    return done;
  }

  const serve = (round: Round, lineId?: string) =>
    run(() => act("POST", `${base}/staff/tabs/${tabId}/orders/${round.id}/serve`, lineId ? { line_ids: [lineId] } : {}, `Serve round ${round.seq_no} at ${view.table_label ?? "a table"}`));

  return (
    <>
      <Link className="back" href={`/o/${outletId}/floor`}>
        <Icon name="back" size={16} />
        All tables
      </Link>
      <PageHeader
        title={`Table ${view.table_label ?? "?"}`}
        subtitle={
          <>
            {tab.data.opened_by === "waiter" ? "Opened by a waiter" : "Opened by the guest"} · {tab.data.guest_sessions} phone
            {tab.data.guest_sessions === 1 ? "" : "s"} on this tab
            {view.status === "bill_requested" ? " · Bill requested" : ""}
          </>
        }
        actions={
          live ? (
            <>
              <Link className="button" href={`/o/${outletId}/floor/${tabId}/add`}>
                Add items
              </Link>
              <button type="button" className="secondary" onClick={() => setPanel(panel === "transfer" ? null : "transfer")}>
                Move to another table
              </button>
              <button type="button" className="secondary" onClick={() => setPanel(panel === "merge" ? null : "merge")}>
                Merge into another tab
              </button>
            </>
          ) : undefined
        }
      />
      <ErrorBanner message={tab.error} />
      {view.status !== "open" && view.status !== "bill_requested" ? <p className="error">This tab is {view.status}.</p> : null}
      {view.awaiting_waiter ? (
        <p className="card">
          The guest is waiting for you to confirm this table.{" "}
          <button type="button" disabled={action.busy} onClick={() => run(() => act("POST", `${base}/tabs/${tabId}/confirm`, undefined, `Confirm table ${view.table_label ?? ""}`))}>
            Confirm table
          </button>
        </p>
      ) : null}
      {mine.length > 0 ? (
        <Card title="Requests">
          {mine.map((r) => (
            <div key={r.id} className="line-row">
              <span className="grow">{humanize(r.type)} · since {timeOf(r.created_at)}</span>
              <button type="button" disabled={action.busy} onClick={() => run(() => act("POST", `${base}/staff/service-requests/${r.id}/resolve`, undefined, `Finish ${humanize(r.type).toLowerCase()} request at ${view.table_label ?? "a table"}`))}>Done</button>
            </div>
          ))}
        </Card>
      ) : null}
      {panel === "transfer" ? (
        <Card title="Move to which table?">
          {freeTables.length === 0 ? <p className="muted">No free tables that you can use.</p> : null}
          <div className="inline">
            {freeTables.map((t) => (
              <button key={t.id} type="button" className="secondary" disabled={action.busy} onClick={async () => { if (await run(() => api(`${base}/staff/tabs/${tabId}/transfer`, { method: "POST", body: { table_id: t.id } }))) setPanel(null); }}>
                {t.label}
              </button>
            ))}
          </div>
        </Card>
      ) : null}
      {panel === "merge" ? (
        <Card title="Merge this tab into which table's tab?">
          <p className="hint">Everything moves to that tab and this one is closed. The guests here follow it.</p>
          {otherTabs.length === 0 ? <p className="muted">No other open tabs.</p> : null}
          <div className="inline">
            {otherTabs.map((t) => (
              <button
                key={t.id}
                type="button"
                className="secondary"
                disabled={action.busy}
                onClick={async () => {
                  if (await run(() => api(`${base}/staff/tabs/${tabId}/merge`, { method: "POST", body: { into_tab_id: t.tab_id } }))) router.replace(`/o/${outletId}/floor/${t.tab_id}`);
                }}
              >
                {t.label}
              </button>
            ))}
          </div>
        </Card>
      ) : null}
      {view.rounds.length === 0 ? (
        <EmptyState title="Nothing ordered yet">
          {live ? "Rounds show up here as the guest orders. Use Add items to order for them." : "Nothing was ordered on this tab."}
        </EmptyState>
      ) : null}
      {view.rounds.map((round) => {
        const anyReady = round.lines.some((l) => l.status === "ready");
        return (
          <Card key={round.id} title={`Round ${round.seq_no} · ${timeOf(round.placed_at)} · ${lineStatus(round.status)}`}>
            {round.lines.map((line) => {
              const gone = line.status === "cancelled" || line.status === "voided";
              return (
                <div key={line.id} className="line-row">
                  <div className="grow">
                    <span className={gone ? "struck" : undefined}>{line.qty} × {line.name}</span>
                    {line.modifiers.length ? <div className="muted">{line.modifiers.map((m) => m.name).join(", ")}</div> : null}
                    {line.note ? <div className="muted">“{line.note}”</div> : null}
                    <div className="muted">
                      {source(line)}
                      {line.price_rule ? ` · ${line.price_rule.name ?? "special price"}` : ""}
                    </div>
                    <div className="badges">
                      <Badge tone={statusTone(line.status)}>{lineStatus(line.status)}</Badge>
                      {line.ack_state === "awaiting" ? <Badge tone="warn">Awaiting the guest&apos;s OK</Badge> : null}
                      {line.ack_state === "acked" ? <Badge tone="ok">Guest confirmed</Badge> : null}
                      {line.ack_state === "disputed" ? (
                        <Badge tone="danger">Guest says this isn&apos;t theirs. A manager will check.</Badge>
                      ) : null}
                    </div>
                    {line.void_reason ? <div className="muted">Removed: {line.void_reason}</div> : null}
                  </div>
                  <div>
                    <div className={gone ? "struck" : undefined}>{formatInr(line.line_total_paise)}</div>
                    {line.status === "ready" ? (
                      <button type="button" disabled={action.busy} onClick={() => serve(round, line.id)}>Serve</button>
                    ) : null}
                  </div>
                </div>
              );
            })}
            {anyReady ? (
              <button type="button" disabled={action.busy} onClick={() => serve(round)}>Serve everything that&apos;s ready</button>
            ) : null}
          </Card>
        );
      })}
      {view.rounds.length > 0 ? (
        <Card title="Total (estimate)">
          <div className="line-row"><span>Items</span><span>{formatInr(view.totals.items_paise)}</span></div>
          {view.totals.service_charge_bp > 0 ? (
            <div className="line-row">
              <span>Service charge</span>
              <span>{view.totals.service_charge_removed ? "Removed by guest" : formatInr(view.totals.service_charge_paise)}</span>
            </div>
          ) : null}
          <div className="line-row"><strong>Total</strong><strong>{formatInr(view.totals.estimated_total_paise)}</strong></div>
          <p className="hint">The bill itself is issued when the tab is closed.</p>
        </Card>
      ) : null}
    </>
  );
}
