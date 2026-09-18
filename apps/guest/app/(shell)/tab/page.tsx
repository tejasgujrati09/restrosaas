"use client";

import { useState } from "react";
import { formatInr } from "@restosaas/ui";
import { TotalsTable } from "@/components/totals";
import { ErrorBanner, Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { secondsUntil, statusLabel, timeOf } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { Line, Round, TabView } from "@/lib/types";
import { useNow } from "@/lib/use-now";
import { useAction, useResource } from "@/lib/use-resource";

function source(line: Line): string {
  if (line.placed_by === "staff") return `${line.staff_name ?? "Staff"} (waiter)`;
  return line.by_you ? "You" : "Someone at your table";
}

export default function TabPage() {
  const session = useSession();
  const path = session ? `/v1/outlets/${session.outlet_id}/tabs/${session.tab_id}` : null;
  const tab = useResource<TabView>(path, 4_000, true);
  const action = useAction();
  const [confirmingBill, setConfirmingBill] = useState(false);
  const undoable = tab.data?.rounds.some((r) => r.undo_until) ?? false;
  const now = useNow(undoable);

  if (!session || !path) return null;
  if (!tab.data) return tab.error ? <ErrorBanner message={tab.error} /> : <Loading what="your tab" />;
  const data = tab.data;

  async function undo(round: Round) {
    if (await action.run(() => api(`${path}/orders/${round.id}/undo`, { method: "POST" }))) tab.reload();
  }

  return (
    <>
      <h1>My tab</h1>
      <p className="muted">Table {data.table_label ?? session.table_label}</p>
      <ErrorBanner message={action.error ?? tab.error} />
      {data.status === "bill_requested" ? (
        <p className="banner" role="status">
          Bill requested. A waiter will bring it shortly. You can still order more.
        </p>
      ) : null}
      {data.awaiting_waiter ? <p className="banner">Waiting for your waiter to confirm this table.</p> : null}
      {data.rounds.length === 0 ? <p>Nothing ordered yet.</p> : null}
      {data.rounds.map((round) => {
        const left = round.undo_until ? secondsUntil(round.undo_until, now) : 0;
        return (
          <section key={round.id} className="card" aria-label={`Round ${round.seq_no}`}>
            <div className="round-head">
              <h2>Round {round.seq_no}</h2>
              <span className="muted">{timeOf(round.placed_at)}</span>
              <span className="status">{statusLabel(round.status)}</span>
            </div>
            {round.lines.map((line) => {
              const gone = line.status === "cancelled" || line.status === "voided";
              return (
                <div key={line.id} className="line">
                  <div className="grow">
                    <span className={gone ? "struck" : undefined}>
                      {line.qty} × {line.name}
                    </span>
                    {line.modifiers.length ? <div className="muted">{line.modifiers.map((m) => m.name).join(", ")}</div> : null}
                    <div className="muted">
                      {source(line)}
                      {line.price_rule ? ` · ${line.price_rule.name ?? "Special price"}` : ""}
                    </div>
                    {line.needs_customer_ack && !line.acked_at ? <div className="deal">Awaiting your ok</div> : null}
                    {line.status === "voided" && line.void_reason ? <div className="muted">Removed: {line.void_reason}</div> : null}
                  </div>
                  <div className={gone ? "struck" : undefined}>{formatInr(line.line_total_paise)}</div>
                </div>
              );
            })}
            {left > 0 && round.lines[0]?.by_you ? (
              <button type="button" className="secondary" disabled={action.busy} onClick={() => undo(round)}>
                Undo ({left}s)
              </button>
            ) : null}
          </section>
        );
      })}
      {data.rounds.length > 0 ? (
        <section className="card" aria-label="Totals">
          <TotalsTable
            totals={data.totals}
            busy={action.busy}
            onToggleServiceCharge={async (removed) => {
              if (await action.run(() => api(`${path}/service-charge`, { method: "PUT", body: { removed } }))) tab.reload();
            }}
          />
          <p className="hint">This is an estimate. Your bill is worked out when it is issued.</p>
        </section>
      ) : null}
      {data.rounds.length > 0 && data.status === "open" ? (
        <button type="button" className="wide" disabled={action.busy} onClick={() => setConfirmingBill(true)}>
          Request the bill
        </button>
      ) : null}
      {confirmingBill ? (
        <div className="banner" role="alertdialog" aria-label="Request the bill">
          <p>Ask for the bill now? You can still order more afterwards.</p>
          <div className="inline">
            <button
              type="button"
              disabled={action.busy}
              onClick={async () => {
                if (await action.run(() => api(`${path}/service-requests`, { method: "POST", body: { type: "bill" } }))) {
                  setConfirmingBill(false);
                  tab.reload();
                }
              }}
            >
              Yes, request it
            </button>{" "}
            <button type="button" className="secondary" onClick={() => setConfirmingBill(false)}>
              Not yet
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
