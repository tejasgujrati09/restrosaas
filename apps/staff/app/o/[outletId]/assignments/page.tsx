"use client";

import { useParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { EmptyState, PageHeader, sentenceCase, Skeleton, toast } from "@restosaas/ui";
import { ErrorBanner, Field } from "@/components/ui";
import { AddTable } from "@/components/add-table";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import { changeNotes, nextLabel, placeholderCount, plural, STRATEGIES, waiterName } from "@/lib/assign";
import { STATE_LABELS } from "@/lib/floor";
import type { AssignmentBoard, AutoStrategy, BoardTable } from "@/lib/types";

const CLEAR = "none";

/** Who serves which table. Tables are cards: pick several, pick a waiter, assign them all at
 *  once. Orders from a table nobody serves either get a waiter automatically (if the outlet
 *  turned that on) or wait here for a manager or host. */
export default function AssignmentsPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}`;
  const board = useResource<AssignmentBoard>(`${base}/table-assignments/board`, undefined, true);
  const action = useAction();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [waiterId, setWaiterId] = useState("");
  const [adding, setAdding] = useState<{ zone: string; key: number } | null>(null);

  const data = board.data;
  // A table that disappeared (deleted elsewhere) cannot stay selected.
  useEffect(() => {
    if (!data) return;
    const ids = new Set(data.tables.map((t) => t.table_id));
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelected((current) => (current.size && [...current].some((id) => !ids.has(id)) ? new Set([...current].filter((id) => ids.has(id))) : current));
  }, [data]);

  if (!data) return board.error ? <ErrorBanner message={board.error} onRetry={board.reload} /> : <Skeleton what="your tables" lines={5} block />;

  const zones = new Map<string, BoardTable[]>();
  for (const t of data.tables) zones.set(t.zone, [...(zones.get(t.zone) ?? []), t]);
  if (zones.size === 0) zones.set("floor", []);
  // "" means nothing chosen yet, CLEAR means take the waiter off, anything else is a waiter.
  const clearing = waiterId === CLEAR;
  const waiter = data.waiters.find((w) => w.user_id === waiterId) ?? null;
  const notes = waiterId === "" ? [] : changeNotes(data.tables, selected, waiter);
  const needing = data.tables.filter((t) => t.needs_waiter);

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleZone(list: BoardTable[]) {
    setSelected((current) => {
      const next = new Set(current);
      const all = list.every((t) => next.has(t.table_id));
      for (const t of list) {
        if (all) next.delete(t.table_id);
        else next.add(t.table_id);
      }
      return next;
    });
  }

  async function assign(tableIds: string[], userId: string, label: string) {
    const ok = await action.run(() =>
      api(`${base}/table-assignments/bulk`, { method: "PUT", body: { table_ids: tableIds, user_ids: userId ? [userId] : [] } }),
    );
    if (ok) {
      toast.ok(label);
      board.reload();
    }
    return ok;
  }

  async function applySelection() {
    const ids = [...selected];
    const label = waiter ? `Assigned ${plural(ids.length, "table")} to ${waiterName(waiter)}.` : `Cleared the waiter from ${plural(ids.length, "table")}.`;
    if (await assign(ids, clearing ? "" : waiterId, label)) { setSelected(new Set()); setWaiterId(""); }
  }

  return (
    <>
      <PageHeader
        title="Assign tables"
        subtitle="Tap tables to select them, then choose a waiter. A waiter sees and takes orders only for their tables; managers and owners see every table."
      />

      <AutoPanel base={base} config={data.config} onSaved={board.reload} />

      {needing.length > 0 ? (
        <section className="alerts" aria-label="Orders waiting for a waiter">
          <h2>Needs a waiter</h2>
          <ul>
            {needing.map((t) => (
              <NeedsWaiter key={t.table_id} table={t} data={data} busy={action.busy} onAssign={(userId, name) => assign([t.table_id], userId, `Table ${t.label} now has ${name}.`)} />
            ))}
          </ul>
        </section>
      ) : null}

      {data.waiters.length === 0 ? <EmptyState title="There are no active waiters yet">Invite some under Staff. You can still add and arrange tables here.</EmptyState> : null}

      {selected.size > 0 ? (
        <div className="assign-bar" role="region" aria-label="Assign the selected tables">
          <strong className="assign-count">{plural(selected.size, "table")} selected</strong>
          <div className="assign-controls">
            <Field label="Waiter">
              <select value={waiterId} onChange={(e) => setWaiterId(e.target.value)}>
                <option value="">Choose a waiter…</option>
                {data.waiters.map((w) => <option key={w.user_id} value={w.user_id}>{waiterName(w)} · {plural(w.tables, "table")}</option>)}
                <option value={CLEAR}>No waiter (clear)</option>
              </select>
            </Field>
            <button type="button" disabled={action.busy || waiterId === ""} onClick={applySelection}>
              {waiter ? `Assign to ${waiterName(waiter)}` : clearing ? "Clear waiter" : "Assign"}
            </button>
            <button type="button" className="tertiary" disabled={action.busy} onClick={() => { setSelected(new Set()); setWaiterId(""); }}>Clear selection</button>
          </div>
          {notes.length > 0 ? (
            <ul className="assign-notes" role="status" aria-label="What will change">
              {notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          ) : null}
        </div>
      ) : null}


      <section aria-label="Tables">
        <div className="zone-head">
          <h2 className="zone">Tables</h2>
          <ul className="legend" aria-label="Table colours">
            {Object.entries(STATE_LABELS).map(([state, label]) => (
              <li key={state}><span className={`swatch state-${state}`} aria-hidden="true" />{label}</li>
            ))}
          </ul>
        </div>
      {[...zones.entries()].map(([zone, list]) => {
        const zoneAll = list.length > 0 && list.every((t) => selected.has(t.table_id));
        return (
          <section key={zone} aria-label={zone}>
            <div className="zone-head">
              <h3 className="zone">{sentenceCase(zone)}</h3>
              {list.length > 0 ? (
                <button type="button" className="tertiary" onClick={() => toggleZone(list)}>
                  {zoneAll ? "Deselect all" : "Select all"}
                </button>
              ) : null}
            </div>
            <div className="tiles roomy">
              {list.map((t) => (
                <button
                  key={t.table_id}
                  type="button"
                  aria-pressed={selected.has(t.table_id)}
                  className={`tile state-${t.state}${selected.has(t.table_id) ? " selected" : ""}`}
                  onClick={() => toggle(t.table_id)}
                >
                  <span className="tile-name">{t.label}</span>
                  <span>{STATE_LABELS[t.state] ?? t.state}</span>
                  <span className="muted">
                    {t.waiters.length ? t.waiters.map((w) => w.name ?? w.phone).join(", ") : "No waiter"}
                  </span>
                  <span className="pills">
                    {selected.has(t.table_id) ? <span className="pill">Selected</span> : null}
                    {t.auto_assigned ? <span className="pill">Picked automatically</span> : null}
                    {t.needs_waiter ? <span className="pill hot">{plural(t.waiting_orders.length, "order")} waiting</span> : null}
                  </span>
                </button>
              ))}
              {Array.from({ length: placeholderCount(data.tables.length) }, (_, i) =>
                adding && adding.zone === zone && i === 0 ? (
                  <AddTable
                    key={`add-${adding.key}`}
                    base={base}
                    zone={zone}
                    suggestion={nextLabel(data.tables.map((t) => t.label))}
                    onDone={() => { setAdding(null); board.reload(); }}
                    onCancel={() => setAdding(null)}
                  />
                ) : (
                  <button key={`slot-${i}`} type="button" className="tile placeholder" onClick={() => setAdding({ zone, key: Date.now() })}>
                    <span className="plus" aria-hidden="true">+</span> Add table
                  </button>
                ),
              )}
            </div>
          </section>
        );
      })}
      </section>
    </>
  );
}

function NeedsWaiter({ table, data, busy, onAssign }: { table: BoardTable; data: AssignmentBoard; busy: boolean; onAssign: (userId: string, name: string) => void }) {
  const [choice, setChoice] = useState("");
  const chosen = data.waiters.find((w) => w.user_id === choice);
  return (
    <li>
      <p>
        <strong>Table {table.label}</strong>: {table.waiting_orders.map((o) => `order #${o.short_id}`).join(", ")}. No waiter yet.
      </p>
      <span className="inline">
        <Field label={`Waiter for table ${table.label}`}>
          <select value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="">Choose…</option>
            {data.waiters.map((w) => <option key={w.user_id} value={w.user_id}>{waiterName(w)} · {plural(w.active_tables, "busy table")}</option>)}
          </select>
        </Field>
        <button type="button" disabled={busy || !chosen} onClick={() => chosen && onAssign(chosen.user_id, waiterName(chosen))}>Assign</button>
      </span>
    </li>
  );
}

function AutoPanel({ base, config, onSaved }: { base: string; config: AssignmentBoard["config"]; onSaved: () => void }) {
  const [enabled, setEnabled] = useState(config.enabled);
  const [strategy, setStrategy] = useState<AutoStrategy>(config.strategy);
  const action = useAction();
  const dirty = enabled !== config.enabled || strategy !== config.strategy;
  const hint = STRATEGIES.find((s) => s.value === strategy)?.hint;

  async function save(event: FormEvent) {
    event.preventDefault();
    if (await action.run(() => api(`${base}/table-assignments/auto`, { method: "PUT", body: { enabled, strategy } }))) onSaved();
  }

  return (
    <form className="card auto-panel" onSubmit={save} aria-label="Orders from tables without a waiter">
      <h2>Orders from tables without a waiter</h2>
      <label className="setting-row">
        <span className="setting-text">
          <strong>Pick a waiter automatically</strong>
          <span className="muted">
            When an order arrives at a table with no waiter, one is picked and told. A table that already has a waiter keeps them. If this is off, or nobody is available, the order waits here for a manager or host.
          </span>
        </span>
        <input type="checkbox" role="switch" className="switch" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
      </label>
      <Field label="How to pick" hint={enabled ? hint : "Used only when automatic assignment is on."} hintLines={2}>
        <select value={strategy} disabled={!enabled} onChange={(e) => setStrategy(e.target.value as AutoStrategy)}>
          {STRATEGIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </Field>
      <div>
        <button type="submit" disabled={!dirty || action.busy}>Save</button>
      </div>
    </form>
  );
}
