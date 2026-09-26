"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { formatInr, Icon, ItemSheet, Notice, PageHeader, Skeleton } from "@restosaas/ui";
import { ErrorBanner } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { act } from "@/lib/offline";
import type { ServeItem, ServeMenu } from "@/lib/types";

type Entry = { key: string; item: ServeItem; qty: number; modifier_ids: string[]; note: string };

/** A waiter adds a round for the guest, from the same menu the guest sees. */
export default function AddItemsPage() {
  const { outletId, tabId } = useParams<{ outletId: string; tabId: string }>();
  const router = useRouter();
  const base = `/v1/outlets/${outletId}`;
  const menu = useResource<ServeMenu>(`${base}/staff/menu`, 30_000, true);
  const [selected, setSelected] = useState<ServeItem | null>(null);
  const [cart, setCart] = useState<Entry[]>([]);
  const [saved, setSaved] = useState<string | null>(null);
  const send = useAction();
  if (!menu.data) return menu.error ? <ErrorBanner message={menu.error} onRetry={menu.reload} /> : <Skeleton what="the menu" lines={6} />;

  const update = setCart;

  /** Sends the round now, or keeps it on this device if there is no connection and sends
   * it when there is (with the same idempotency key, so it cannot be placed twice). */
  async function place() {
    const lines = cart.map((e) => ({ menu_item_id: e.item.id, qty: e.qty, modifier_ids: e.modifier_ids, note: e.note || null }));
    const summary = cart.map((e) => `${e.qty} × ${e.item.name}`).join(", ");
    const outcome = await send.call(() => act("POST", `${base}/staff/tabs/${tabId}/orders`, { lines }, `Add ${summary}`));
    if (outcome === "sent") router.replace(`/o/${outletId}/floor/${tabId}`);
    if (outcome === "queued") {
      // Stay put: with no connection, going to another screen may not load.
      setCart([]);
      setSaved(summary);
    }
  }

  return (
    <>
      <Link className="back" href={`/o/${outletId}/floor/${tabId}`} aria-label="Back to table">
        <Icon name="back" size={16} />
        Table
      </Link>
      <PageHeader title="Add items" subtitle="Your name goes on each item. Items of ₹500 or more ask the guest to confirm." />
      <ErrorBanner message={send.error ?? menu.error} />
      {saved ? (
        <Notice>
          Saved on this device: {saved}. It will be sent as soon as you are back online.{" "}
          <Link href={`/o/${outletId}/floor/${tabId}`}>Back to the table</Link>
        </Notice>
      ) : null}
      {cart.length > 0 ? (
        <section className="card" aria-label="This round">
          <h2>This round</h2>
          {cart.map((e) => (
            <div key={e.key} className="line-row">
              <div className="grow">
                <strong>{e.item.name}</strong>
                {e.modifier_ids.length ? <div className="muted">{e.item.modifier_groups.flatMap((g) => g.modifiers).filter((m) => e.modifier_ids.includes(m.id)).map((m) => m.name).join(", ")}</div> : null}
                {e.note ? <div className="muted">“{e.note}”</div> : null}
              </div>
              <div className="qty" role="group" aria-label={`Quantity of ${e.item.name}`}>
                <button
                  type="button"
                  className="secondary icon-btn"
                  aria-label={e.qty === 1 ? `Remove ${e.item.name}` : `One less ${e.item.name}`}
                  onClick={() => update(cart.flatMap((c) => (c.key !== e.key ? [c] : c.qty > 1 ? [{ ...c, qty: c.qty - 1 }] : [])))}
                >
                  <Icon name={e.qty === 1 ? "close" : "minus"} />
                </button>
                <output>{e.qty}</output>
                <button
                  type="button"
                  className="secondary icon-btn"
                  aria-label={`One more ${e.item.name}`}
                  onClick={() => update(cart.map((c) => (c.key === e.key ? { ...c, qty: Math.min(50, c.qty + 1) } : c)))}
                >
                  <Icon name="plus" />
                </button>
              </div>
            </div>
          ))}
          <button type="button" className="btn-lg wide cta" disabled={send.busy} onClick={place}>{send.busy ? "Sending…" : "Send to the kitchen"}</button>
        </section>
      ) : null}
      {menu.data.categories.map((c) => (
        <section key={c.id} className="card">
          <h2>{c.name}</h2>
          {c.items.map((item) => (
            <div key={item.id} className="line-row center">
              <div className="grow">
                {item.name}
                {item.price_rule ? <div className="warn">{item.price_rule.name}</div> : null}
                {!item.available ? <div className="muted">Sold out</div> : !item.self_orderable ? <div className="muted">Needs a manager</div> : null}
              </div>
              <div className="inline">
                <span className="money">{formatInr(item.price_paise)}</span>
                <button type="button" className="secondary" disabled={!item.available} onClick={() => setSelected(item)}>Add</button>
              </div>
            </div>
          ))}
        </section>
      ))}
      <ItemSheet
        item={selected}
        canOrder
        onClose={() => setSelected(null)}
        onAdd={(entry) => {
          if (selected) update([...cart, { key: crypto.randomUUID(), item: selected, ...entry }]);
          setSelected(null);
        }}
      />
    </>
  );
}
