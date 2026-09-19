"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { formatInr, ItemSheet } from "@restosaas/ui";
import { ErrorBanner } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api, ApiError } from "@/lib/api";
import type { Round, ServeItem, ServeMenu } from "@/lib/types";

type Entry = { key: string; item: ServeItem; qty: number; modifier_ids: string[]; note: string };

/** A waiter adds a round for the guest, from the same menu the guest sees. */
export default function AddItemsPage() {
  const { outletId, tabId } = useParams<{ outletId: string; tabId: string }>();
  const router = useRouter();
  const base = `/v1/outlets/${outletId}`;
  const menu = useResource<ServeMenu>(`${base}/staff/menu`, 30_000, true);
  const [selected, setSelected] = useState<ServeItem | null>(null);
  const [cart, setCart] = useState<Entry[]>([]);
  const send = useAction();
  // One key per attempt: a double tap or a retry after a dropped connection sends the same
  // key, so the round is placed once. It resets when the cart changes.
  const key = useRef<string | null>(null);

  if (!menu.data) return <ErrorBanner message={menu.error} />;

  const update = (next: Entry[]) => {
    key.current = null;
    setCart(next);
  };

  async function place() {
    key.current ??= crypto.randomUUID();
    const lines = cart.map((e) => ({ menu_item_id: e.item.id, qty: e.qty, modifier_ids: e.modifier_ids, note: e.note || null }));
    const round = await send.call(async () => {
      try {
        return await api<Round>(`${base}/staff/tabs/${tabId}/orders`, { method: "POST", body: { lines }, idempotencyKey: key.current ?? undefined });
      } catch (e) {
        if (e instanceof ApiError && e.status < 500) key.current = null;
        throw e;
      }
    });
    if (round) router.replace(`/o/${outletId}/floor/${tabId}`);
  }

  return (
    <>
      <p><Link href={`/o/${outletId}/floor/${tabId}`}>← Back to the table</Link></p>
      <h1>Add items</h1>
      <ErrorBanner message={send.error ?? menu.error} />
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
              <div className="inline">
                <button type="button" className="secondary" aria-label={`One less ${e.item.name}`} onClick={() => update(cart.flatMap((c) => (c.key !== e.key ? [c] : c.qty > 1 ? [{ ...c, qty: c.qty - 1 }] : [])))}>
                  {e.qty === 1 ? "Remove" : "−"}
                </button>
                <output>{e.qty}</output>
                <button type="button" className="secondary" aria-label={`One more ${e.item.name}`} onClick={() => update(cart.map((c) => (c.key === e.key ? { ...c, qty: Math.min(50, c.qty + 1) } : c)))}>+</button>
              </div>
            </div>
          ))}
          <button type="button" disabled={send.busy} onClick={place}>{send.busy ? "Sending…" : "Send to the kitchen"}</button>
          <p className="hint">Your name goes on each item. Items of ₹500 or more ask the guest to confirm.</p>
        </section>
      ) : null}
      {menu.data.categories.map((c) => (
        <section key={c.id} className="card">
          <h2>{c.name}</h2>
          {c.items.map((item) => (
            <div key={item.id} className="line-row">
              <div className="grow">
                {item.name}
                {item.price_rule ? <div className="warn">{item.price_rule.name}</div> : null}
                {!item.available ? <div className="muted">Sold out</div> : !item.self_orderable ? <div className="muted">Needs a manager</div> : null}
              </div>
              <div className="inline">
                <span>{formatInr(item.price_paise)}</span>
                <button type="button" disabled={!item.available} onClick={() => setSelected(item)}>Add</button>
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
