"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { TotalsTable } from "@/components/totals";
import { EmptyState, ErrorBanner, Notice } from "@/components/ui";
import { formatInr, Icon } from "@restosaas/ui";
import { api, errorMessage, isRetryable } from "@/lib/api";
import { setQty, useCart, writeCart } from "@/lib/cart-store";
import { secondsUntil, timeOf } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { Quote, Round } from "@/lib/types";
import { useNow } from "@/lib/use-now";
import { useAction } from "@/lib/use-resource";

export default function CartPage() {
  const session = useSession();
  const entries = useCart(session?.tab_id ?? null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [placed, setPlaced] = useState<Round | null>(null);
  const place = useAction();
  const charge = useAction();
  const undo = useAction();
  const [undone, setUndone] = useState(false);
  // One key per attempt: a double tap or a retry after a dropped connection sends the same
  // key, so the server places the round once. It resets whenever the cart changes.
  const key = useRef<string | null>(null);
  const lines = JSON.stringify(entries.map(({ menu_item_id, qty, modifier_ids, note }) => ({ menu_item_id, qty, modifier_ids, note: note || null })));

  useEffect(() => {
    key.current = null;
  }, [lines]);

  useEffect(() => {
    if (!session || entries.length === 0) return;
    let cancelled = false;
    api<Quote>(`/v1/outlets/${session.outlet_id}/tabs/${session.tab_id}/cart/quote`, {
      method: "POST",
      body: { lines: JSON.parse(lines) },
    })
      .then((q) => {
        if (!cancelled) {
          setQuote(q);
          setQuoteError(null);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setQuoteError(errorMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [session, lines, entries.length, refresh]);

  const now = useNow(placed !== null && !undone);
  if (!session) return null;
  const tabPath = `/v1/outlets/${session.outlet_id}/tabs/${session.tab_id}`;

  if (placed) {
    const left = placed.undo_until && !undone ? secondsUntil(placed.undo_until, now) : 0;
    return (
      <section className="confirm" aria-live="polite">
        {undone ? (
          <>
            <p className="big">Order cancelled</p>
            <p>Nothing was sent to the kitchen.</p>
          </>
        ) : (
          <>
            <span className="mark" aria-hidden="true">
              <Icon name="check" size={28} />
            </span>
            <p className="big">Order placed</p>
            <p>
              Round {placed.seq_no} · {timeOf(placed.placed_at)}
            </p>
            {left > 0 ? (
              <>
                <p className="muted">Changed your mind? You can undo for {left} more seconds.</p>
                <ErrorBanner message={undo.error} />
                <button
                  type="button"
                  className="secondary"
                  disabled={undo.busy}
                  onClick={async () => {
                    const done = await undo.run(() => api<Round>(`${tabPath}/orders/${placed.id}/undo`, { method: "POST" }));
                    if (done) setUndone(true);
                  }}
                >
                  Undo this order
                </button>
              </>
            ) : null}
          </>
        )}
        <div className="actions">
          <Link className="button btn-lg" href="/tab">
            See my tab
          </Link>
          <Link className="button secondary btn-lg" href="/menu">
            Back to menu
          </Link>
        </div>
      </section>
    );
  }

  async function placeOrder() {
    key.current ??= crypto.randomUUID();
    const round = await place.run(async () => {
      try {
        return await api<Round>(`${tabPath}/orders`, {
          method: "POST",
          body: { lines: JSON.parse(lines) },
          idempotencyKey: key.current ?? undefined,
        });
      } catch (e) {
        // A definite refusal (unavailable item, unconfirmed table) needs a fresh key next time;
        // a dropped connection keeps the key so the retry cannot order twice.
        if (!isRetryable(e)) key.current = null;
        throw e;
      }
    });
    if (round) {
      key.current = null;
      writeCart(session!.tab_id, []);
      setPlaced(round);
    }
  }

  if (entries.length === 0) {
    return (
      <>
        <header className="g-head with-back">
          <Link className="button secondary icon-btn" href="/menu" aria-label="Back to menu">
            <Icon name="back" />
          </Link>
          <h1>Your cart</h1>
        </header>
        <EmptyState
          title="Nothing in your cart yet"
          action={
            <Link className="button" href="/menu">
              Browse the menu
            </Link>
          }
        >
          Add something from the menu and it will show up here.
        </EmptyState>
      </>
    );
  }

  return (
    <>
      <header className="g-head with-back">
        <Link className="button secondary icon-btn" href="/menu" aria-label="Back to menu">
          <Icon name="back" />
        </Link>
        <div>
          <h1>Your cart</h1>
          <p className="sub">This round for table {session.table_label}</p>
        </div>
      </header>
      <ErrorBanner message={quoteError} />
      <section aria-label="Items">
        {entries.map((e) => {
          const priced = quote?.lines.find((l) => l.menu_item_id === e.menu_item_id && l.qty === e.qty);
          return (
            <div key={e.key} className="card line-card">
              <div className="top">
                <div className="grow">
                  <strong>{e.name}</strong>
                  {priced?.modifiers.length ? <div className="muted">{priced.modifiers.map((m) => m.name).join(", ")}</div> : null}
                  {priced?.price_rule ? <div className="deal">{priced.price_rule.name}</div> : null}
                  {e.note ? <div className="muted">“{e.note}”</div> : null}
                </div>
                <strong>{priced ? formatInr(priced.line_total_paise) : "…"}</strong>
              </div>
              <div className="controls">
                <div className="qty" role="group" aria-label={`Quantity of ${e.name}`}>
                  <button
                    type="button"
                    className="secondary icon-btn"
                    aria-label={`One less ${e.name}`}
                    disabled={e.qty <= 1}
                    onClick={() => setQty(session.tab_id, e.key, e.qty - 1)}
                  >
                    <Icon name="minus" />
                  </button>
                  <output>{e.qty}</output>
                  <button
                    type="button"
                    className="secondary icon-btn"
                    aria-label={`One more ${e.name}`}
                    onClick={() => setQty(session.tab_id, e.key, e.qty + 1)}
                  >
                    <Icon name="plus" />
                  </button>
                </div>
                <button type="button" className="tertiary" aria-label={`Remove ${e.name}`} onClick={() => setQty(session.tab_id, e.key, 0)}>
                  Remove
                </button>
              </div>
            </div>
          );
        })}
      </section>
      {quote ? (
        <section className="card" aria-label="Totals">
          <TotalsTable
            totals={quote.totals}
            busy={charge.busy}
            onToggleServiceCharge={async (removed) => {
              const done = await charge.run(() => api(`${tabPath}/service-charge`, { method: "PUT", body: { removed } }));
              if (done !== undefined) setRefresh((n) => n + 1);
            }}
          />
          <p className="hint">Final tax and the bill are worked out when you ask for the bill.</p>
        </section>
      ) : null}
      <ErrorBanner message={charge.error ?? place.error} />
      {quote && !quote.can_order ? <Notice>Your waiter needs to confirm your table before you can order.</Notice> : null}
      <button type="button" className="btn-lg cta" disabled={!quote || !quote.can_order || place.busy} onClick={placeOrder}>
        <span>{place.busy ? "Placing…" : "Place order"}</span>
        {quote && !place.busy ? <span>{formatInr(quote.totals.estimated_total_paise)}</span> : null}
      </button>
    </>
  );
}
