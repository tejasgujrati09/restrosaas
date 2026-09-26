"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { Badge, EmptyState, PageHeader, Skeleton } from "@restosaas/ui";
import { ErrorBanner } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { act } from "@/lib/offline";
import { api } from "@/lib/api";
import { ageClass, minutesSince, secondsUntil } from "@/lib/floor";
import { useStored } from "@/lib/stored";
import type { Menu, Ticket, TicketQueue } from "@/lib/types";
import { useNow } from "@/lib/use-now";

/** The bar and kitchen queue: oldest on the left, one tap to start or bump. No prices. */
export default function KitchenPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}`;
  const [station, setStation] = useStored(`restosaas.station.${outletId}`);
  const menu = useResource<Menu>(`${base}/menu`, undefined, true);
  const queue = useResource<TicketQueue>(`${base}/tickets${station ? `?station_id=${station}` : ""}`, 10_000, true);
  const action = useAction();
  const now = useNow();
  const [search, setSearch] = useState("");
  const [note, setNote] = useState<string | null>(null);

  if (!queue.data) return queue.error ? <ErrorBanner message={queue.error} onRetry={queue.reload} /> : <Skeleton what="the queue" lines={3} block />;

  async function move(t: Ticket, verb: "start" | "ready" | "recall") {
    if (await action.run(() => act("POST", `${base}/tickets/${t.id}/${verb}`, undefined, `${verb[0]?.toUpperCase()}${verb.slice(1)} ticket for table ${t.table_label ?? "?"}`))) queue.reload();
  }

  async function soldOut(itemId: string, name: string, sold: boolean) {
    if (await action.run(() => api(`${base}/items/${itemId}/sold-out`, { method: "PUT", body: { sold_out: sold } }))) {
      setNote(sold ? `${name} is marked sold out. Guests and waiters see it now.` : `${name} is available again.`);
      menu.reload();
    }
  }

  const items = (menu.data?.categories ?? []).flatMap((c) => c.items).filter((i) => i.name.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <>
      <PageHeader title="Kitchen and bar" subtitle={queue.data.queue.length > 0 ? `${queue.data.queue.length} ticket${queue.data.queue.length === 1 ? "" : "s"} waiting` : undefined} />
      <ErrorBanner message={queue.error} />
      <div className="stations" role="group" aria-label="Station">
        <button type="button" className="secondary" aria-pressed={station === null} onClick={() => setStation(null)}>Everything</button>
        {(menu.data?.stations ?? []).map((s) => (
          <button key={s.id} type="button" className="secondary" aria-pressed={station === s.id} onClick={() => setStation(s.id)}>{s.name}</button>
        ))}
      </div>
      {queue.data.queue.length === 0 ? (
        <EmptyState title="No tickets waiting.">New orders show up here the moment a guest or waiter places them.</EmptyState>
      ) : null}
      <div className="tickets">
        {queue.data.queue.map((t) => {
          const minutes = minutesSince(t.created_at, now);
          const hold = t.holding_until ? secondsUntil(t.holding_until, now) : 0;
          const phone = t.source === "voice";
          const waitingForAcceptance = phone && t.status === "queued" && !t.can_start;
          const holding = t.status === "queued" && !t.can_start && !phone;
          return (
            <article
              key={t.id}
              className={`ticket ${holding || waitingForAcceptance ? "holding" : ageClass(minutes)}`}
              aria-label={phone ? `Phone order round ${t.seq_no}` : `Table ${t.table_label ?? "?"} round ${t.seq_no}`}
            >
              <h3>
                {phone ? "Phone order" : `Table ${t.table_label ?? "?"}`} <span className="muted">· round {t.seq_no}</span>
              </h3>
              <p className="muted">
                {t.station_name ?? "Any station"} · {minutes} min
              </p>
              {t.lines.map((l, i) => (
                <div key={i}>
                  <p className="item-line">{l.qty} × {l.name}</p>
                  {l.modifiers.map((m) => (
                    <p key={m} className="sub">+ {m}</p>
                  ))}
                  {l.note ? <p className="sub">“{l.note}”</p> : null}
                </div>
              ))}
              {holding ? <p className="hold">The guest can still undo for {hold}s. Start unlocks then.</p> : null}
              {waitingForAcceptance ? <p className="hold">A manager or the owner has to accept this phone order first. Start unlocks then.</p> : null}
              {t.status === "queued" ? (
                <button type="button" className="big" disabled={action.busy || !t.can_start} onClick={() => move(t, "start")}>
                  {t.can_start ? "Start" : waitingForAcceptance ? "Not accepted yet" : `Wait ${hold}s`}
                </button>
              ) : (
                <button type="button" className="big" disabled={action.busy} onClick={() => move(t, "ready")}>Ready</button>
              )}
            </article>
          );
        })}
      </div>
      {queue.data.recent.length > 0 ? (
        <section className="card" aria-label="Recently bumped">
          <h2>Just bumped</h2>
          {queue.data.recent.map((t) => (
            <div key={t.id} className="line-row">
              <span className="grow">Table {t.table_label ?? "?"} · round {t.seq_no} · {t.lines.map((l) => `${l.qty} × ${l.name}`).join(", ")}</span>
              <button type="button" className="secondary" disabled={action.busy} onClick={() => move(t, "recall")}>Recall</button>
            </div>
          ))}
        </section>
      ) : null}
      <section className="card" aria-label="Sold out">
        <h2>Sold out</h2>
        {note ? <p role="status" className="ok">{note}</p> : null}
        <input type="search" aria-label="Find an item" placeholder="Find an item" value={search} onChange={(e) => setSearch(e.target.value)} />
        {items.slice(0, 40).map((i) => (
          <div key={i.id} className="line-row">
            <span className="grow">{i.name} {!i.available ? <Badge tone="danger">Sold out</Badge> : null}</span>
            <button type="button" className="secondary" disabled={action.busy} onClick={() => soldOut(i.id, i.name, i.available)}>
              {i.available ? "Mark sold out" : "Available again"}
            </button>
          </div>
        ))}
      </section>
    </>
  );
}
