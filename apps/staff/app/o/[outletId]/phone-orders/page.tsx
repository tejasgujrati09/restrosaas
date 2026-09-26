"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { Badge, EmptyState, Field, Money, Notice, PageHeader, Skeleton } from "@restosaas/ui";
import { ErrorBanner } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import { minutesSince, timeOf } from "@/lib/floor";
import type { VoiceOrder } from "@/lib/types";
import { useNow } from "@/lib/use-now";

/** Orders taken by the phone assistant. Each waits here until a manager or the owner accepts
 *  it; only then can the kitchen start it. Nothing is accepted by a timer. */
export default function PhoneOrdersPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}/staff/voice-orders`;
  const feed = useResource<VoiceOrder[]>(base, 15_000, true);
  const action = useAction();
  const now = useNow();
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState<string | null>(null);

  if (!feed.data) return feed.error ? <ErrorBanner message={feed.error} onRetry={feed.reload} /> : <Skeleton what="phone orders" lines={3} block />;

  async function accept(o: VoiceOrder) {
    if (await action.run(() => api(`${base}/${o.order_id}/accept`, { method: "POST" }))) {
      setNote("Order accepted. The kitchen can start it now.");
      feed.reload();
    }
  }

  async function reject(o: VoiceOrder) {
    if (await action.run(() => api(`${base}/${o.order_id}/reject`, { method: "POST", body: { reason: reason.trim() } }))) {
      setNote("Order rejected. Call the customer back if they should know.");
      setRejecting(null);
      setReason("");
      feed.reload();
    }
  }

  return (
    <>
      <PageHeader
        title="Phone orders"
        subtitle={
          feed.data.length > 0
            ? `${feed.data.length} waiting for you to accept`
            : "Orders taken by the phone assistant wait here until you accept them."
        }
      />
      <ErrorBanner message={feed.error} />
      {note ? <Notice tone="info">{note}</Notice> : null}
      {feed.data.length === 0 ? (
        <EmptyState title="No phone orders waiting.">
          When a customer orders by phone, it shows up here. The kitchen only sees it to start after you accept it.
        </EmptyState>
      ) : null}
      {feed.data.map((o) => {
        const waited = Math.max(minutesSince(o.placed_at, now), 0);
        const delivery = o.fulfillment_type === "delivery";
        const asking = rejecting === o.order_id;
        return (
          <section key={o.order_id} className="card ticket" aria-label={`Phone order from ${o.customer_name ?? o.customer_phone ?? "a caller"}`}>
            <h3>
              {o.customer_name ?? "Caller"} <span className="muted">· {o.customer_phone ?? "number not available"}</span>
            </h3>
            <p className="inline">
              <Badge tone="warn">Waiting for you</Badge>
              <Badge tone="info">{delivery ? "Delivery" : "Pickup"}</Badge>
            </p>
            <p className="muted">
              Placed {timeOf(o.placed_at)} · {waited} min ago
            </p>
            {delivery ? <p>{o.delivery_address ?? "No address was given. Call the customer."}</p> : null}
            {o.lines.map((l, i) => (
              <p key={i} className="line-row">
                <span className="grow">
                  {l.qty} × {l.name}
                </span>
                <Money paise={l.line_total_paise} />
              </p>
            ))}
            <p className="line-row">
              <strong className="grow">Items total</strong>
              <strong>
                <Money paise={o.total_paise} />
              </strong>
            </p>
            {asking ? (
              <>
                <Field label="Why are you rejecting it?" hint="This is saved with the order.">
                  <input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} autoFocus />
                </Field>
                <div className="inline">
                  <button type="button" className="danger-solid" disabled={action.busy || reason.trim() === ""} onClick={() => reject(o)}>
                    Reject order
                  </button>
                  <button type="button" className="secondary" disabled={action.busy} onClick={() => setRejecting(null)}>
                    Keep it
                  </button>
                </div>
              </>
            ) : (
              <div className="inline">
                <button type="button" disabled={action.busy} onClick={() => accept(o)}>
                  Accept order
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={action.busy}
                  onClick={() => {
                    setRejecting(o.order_id);
                    setReason("");
                  }}
                >
                  Reject…
                </button>
              </div>
            )}
          </section>
        );
      })}
    </>
  );
}
