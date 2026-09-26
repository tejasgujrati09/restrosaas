"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, formatInr, Sheet, type Tone } from "@restosaas/ui";
import { TotalsTable } from "@/components/totals";
import { EmptyState, ErrorBanner, Notice, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { secondsUntil, statusLabel, timeOf } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { Line, Round, TabView } from "@/lib/types";
import { useNow } from "@/lib/use-now";
import { useAction, useResource } from "@/lib/use-resource";

const STATUS_TONE: Record<string, Tone> = {
  placed: "info",
  accepted: "neutral",
  preparing: "warn",
  ready: "ok",
  served: "ok",
  cancelled: "neutral",
  voided: "neutral",
};

/** Kitchen progress worth showing per item; earlier and final states are on the round. */
const LINE_PROGRESS = new Set(["preparing", "ready", "served"]);

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
  if (!tab.data) return tab.error ? <ErrorBanner message={tab.error} onRetry={tab.reload} /> : <Skeleton what="your tab" block lines={3} />;
  const data = tab.data;

  async function answer(line: Line, answer: "ours" | "not_ours") {
    if (await action.run(() => api(`${path}/lines/${line.id}/ack`, { method: "POST", body: { answer } }))) tab.reload();
  }

  async function undo(round: Round) {
    if (await action.run(() => api(`${path}/orders/${round.id}/undo`, { method: "POST" }))) tab.reload();
  }

  return (
    <>
      <header className="g-head">
        <div>
          <h1>My tab</h1>
          <p className="sub">Table {data.table_label ?? session.table_label}</p>
        </div>
        {data.rounds.length > 0 ? (
          <div className="running">
            <span className="sub">Running total</span>
            <strong className="money">{formatInr(data.totals.estimated_total_paise)}</strong>
          </div>
        ) : null}
      </header>
      <ErrorBanner message={tab.error} />
      {data.status === "bill_requested" ? (
        <Notice tone="info">Bill requested. A waiter will bring it shortly. You can still order more.</Notice>
      ) : null}
      {data.awaiting_waiter ? <Notice>Waiting for your waiter to confirm this table.</Notice> : null}
      {data.rounds.length === 0 ? (
        <EmptyState
          title="Nothing ordered yet"
          action={
            <Link className="button" href="/menu">
              Browse the menu
            </Link>
          }
        >
          Your rounds will show up here as soon as you place an order.
        </EmptyState>
      ) : null}
      {data.rounds.map((round) => {
        const left = round.undo_until ? secondsUntil(round.undo_until, now) : 0;
        return (
          <section key={round.id} className="card" aria-label={`Round ${round.seq_no}`}>
            <div className="round-head">
              <h2>Round {round.seq_no}</h2>
              <span className="muted">{timeOf(round.placed_at)}</span>
              <Badge tone={STATUS_TONE[round.status] ?? "neutral"}>{statusLabel(round.status)}</Badge>
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
                    {LINE_PROGRESS.has(line.status) ? (
                      <div>
                        <Badge tone={STATUS_TONE[line.status] ?? "neutral"}>{statusLabel(line.status)}</Badge>
                      </div>
                    ) : null}
                    {line.ack_state === "awaiting" ? (
                      <div className="ack" role="group" aria-label={`Is ${line.name} yours?`}>
                        <p>Your waiter added this. Is it yours?</p>
                        <div className="inline">
                          <button type="button" disabled={action.busy} onClick={() => answer(line, "ours")}>
                            Yes, ours
                          </button>
                          <button type="button" className="secondary" disabled={action.busy} onClick={() => answer(line, "not_ours")}>
                            Not ours
                          </button>
                        </div>
                      </div>
                    ) : null}
                    {line.ack_state === "acked" ? <div className="muted">You confirmed this.</div> : null}
                    {line.ack_state === "disputed" ? <div className="deal">You said this isn&apos;t yours. A manager will check.</div> : null}
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
        <button type="button" className="btn-lg cta" disabled={action.busy} onClick={() => setConfirmingBill(true)}>
          <span>Request the bill</span>
          <span>{formatInr(data.totals.estimated_total_paise)}</span>
        </button>
      ) : null}
      <Sheet open={confirmingBill} onClose={() => setConfirmingBill(false)} title="Ask for the bill?">
        <p className="muted">You can still order more afterwards.</p>
        <div className="stack">
          <button
            type="button"
            className="btn-lg"
            disabled={action.busy}
            onClick={async () => {
              if (await action.run(() => api(`${path}/service-requests`, { method: "POST", body: { type: "bill" } }))) {
                setConfirmingBill(false);
                tab.reload();
              }
            }}
          >
            Yes, request it
          </button>
          <button type="button" className="secondary btn-lg" onClick={() => setConfirmingBill(false)}>
            Not yet
          </button>
        </div>
      </Sheet>
    </>
  );
}
