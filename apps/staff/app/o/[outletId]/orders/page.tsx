"use client";

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Badge, Card, EmptyState, Field, Icon, Money, Notice, PageHeader, Sheet, Skeleton, TabStrip } from "@restosaas/ui";
import { ErrorBanner } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import { timeOf } from "@/lib/floor";
import { ORDER_TABS, PAGE_SIZE, SOURCES, daysBefore, emptyText, ordersPath, sourceLabel, statusView, summariseItems, taxLabel, ticketText } from "@/lib/orders";
import type { OrderDetail, OrderGroup, OrderRow, OrdersList } from "@/lib/types";
import { useDebounced } from "@/lib/use-debounced";

/** Every order for this outlet, whatever its source, in the tabs an owner works through. Counts
 *  and rows share one date window; the list refetches whenever the server pushes a change. */
export default function OrdersPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const [group, setGroup] = useState<OrderGroup>("new");
  const [source, setSource] = useState("");
  const [search, setSearch] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [offset, setOffset] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const q = useDebounced(search);

  const path = ordersPath(outletId, { group, source, q, from, to, offset });
  const feed = useResource<OrdersList>(path, 30_000, true);
  const data = feed.data;

  // A short, polite heads-up when something new arrives while this page is open.
  const seenNew = useRef<number | null>(null);
  const [arrived, setArrived] = useState(0);
  const newCount = data?.counts.new;
  useEffect(() => {
    if (newCount === undefined) return;
    if (seenNew.current !== null && newCount > seenNew.current) setArrived(newCount - seenNew.current);
    seenNew.current = newCount;
  }, [newCount]);

  function choose(next: OrderGroup) {
    setGroup(next);
    setOffset(0);
    setArrived(0);
  }

  const filtered = source !== "" || q.trim() !== "";
  return (
    <>
      <PageHeader title="Orders" subtitle="Everything coming in, and where it is up to." />
      <form className="filters" role="search" onSubmit={(e) => e.preventDefault()}>
        <Field label="Search" hint="Order number, customer, phone or table">
          <input
            type="search"
            value={search}
            maxLength={60}
            onChange={(e) => {
              setSearch(e.target.value);
              setOffset(0);
            }}
          />
        </Field>
        <Field label="Source">
          <select
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All sources</option>
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {sourceLabel(s)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="From" hint={from === "" ? "Today" : undefined}>
          <input type="date" value={from} onChange={(e) => (setFrom(e.target.value), setOffset(0))} />
        </Field>
        <Field label="To">
          <input type="date" value={to} min={from || undefined} onChange={(e) => (setTo(e.target.value), setOffset(0))} />
        </Field>
        {from !== "" || to !== "" ? (
          <button
            type="button"
            className="tertiary"
            onClick={() => {
              setFrom("");
              setTo("");
              setOffset(0);
            }}
          >
            Back to today
          </button>
        ) : null}
      </form>

      <ErrorBanner message={feed.error} />
      {feed.error && !data ? (
        <button type="button" className="secondary" onClick={feed.reload}>
          Try again
        </button>
      ) : null}
      {arrived > 0 ? (
        <Notice tone="info">
          {arrived === 1 ? "A new order just arrived." : `${arrived} new orders just arrived.`}
        </Notice>
      ) : null}

      {!data && !feed.error ? <Skeleton what="orders" lines={4} block /> : null}
      {data ? (
        <>
          <TabStrip
            label="Order status"
            value={group}
            onChange={choose}
            tabs={ORDER_TABS.map((t) => ({ ...t, count: data.counts[t.key] }))}
          />
          {data.earlier_open > 0 ? (
            <Notice tone="warn">
              {data.earlier_open === 1 ? "1 order from before" : `${data.earlier_open} orders from before`} {data.date_from} {data.earlier_open === 1 ? "is" : "are"} still open.{" "}
              <button
                type="button"
                className="tertiary"
                onClick={() => {
                  setFrom(daysBefore(data.date_from, 7));
                  setTo(data.date_to);
                  setOffset(0);
                }}
              >
                Look back 7 days
              </button>
            </Notice>
          ) : null}
          <section role="tabpanel" aria-labelledby={`tab-${group}`}>
            {data.orders.length === 0 ? (
              <EmptyState title={filtered ? "No orders match." : emptyText(group)}>
                {filtered ? "Clear the search or the source to see more." : "This list updates by itself."}
              </EmptyState>
            ) : (
              <ul className="orders">
                {data.orders.map((o) => (
                  <li key={o.id}>
                    <OrderCard order={o} onOpen={() => setOpenId(o.id)} />
                  </li>
                ))}
              </ul>
            )}
            {offset > 0 || data.has_more ? (
              <div className="inline">
                <button type="button" className="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                  Newer
                </button>
                <button type="button" className="secondary" disabled={!data.has_more} onClick={() => setOffset(offset + PAGE_SIZE)}>
                  Older
                </button>
              </div>
            ) : null}
          </section>
        </>
      ) : null}

      <OrderSheet outletId={outletId} orderId={openId} onClose={() => setOpenId(null)} onChanged={feed.reload} />
    </>
  );
}

function OrderCard({ order: o, onOpen }: { order: OrderRow; onOpen: () => void }) {
  const status = statusView(o.status);
  const { shown, more } = summariseItems(o.items);
  const who = o.customer_name ?? o.customer_phone ?? (o.table_label ? `Table ${o.table_label}` : "Guest");
  return (
    <button type="button" className="card order-card" onClick={onOpen} aria-label={`Order ${o.short_id}, ${status.label}, ${who}`}>
      <span className="line-row">
        <strong className="grow">#{o.short_id}</strong>
        <span className="muted">{timeOf(o.placed_at)}</span>
      </span>
      <span className="inline">
        <Badge tone={o.source === "voice" ? "info" : "neutral"}>
          {o.source === "voice" ? <Icon name="phone" /> : null}
          {sourceLabel(o.source)}
        </Badge>
        <Badge tone={status.tone}>{status.label}</Badge>
        {o.fulfillment_type !== "dine_in" ? <Badge tone="neutral">{o.fulfillment_type === "delivery" ? "Delivery" : "Pickup"}</Badge> : null}
      </span>
      <span className="muted">{who}{o.table_label && o.customer_name ? ` · Table ${o.table_label}` : ""}</span>
      <span className="items">
        {shown.map((line, i) => (
          <span key={`${i}-${line}`}>{line}</span>
        ))}
        {more > 0 ? <span className="muted">+ {more} more</span> : null}
      </span>
      <span className="line-row">
        <span className="grow muted">Total</span>
        <strong>
          <Money paise={o.total_paise} />
        </strong>
      </span>
    </button>
  );
}

function OrderSheet({
  outletId,
  orderId,
  onClose,
  onChanged,
}: {
  outletId: string;
  orderId: string | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const detail = useResource<OrderDetail>(orderId ? `/v1/outlets/${outletId}/staff/orders/${orderId}` : null, 30_000, true);
  const action = useAction();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const d = orderId ? detail.data : null;

  async function act(run: () => Promise<unknown>) {
    if (await action.run(run)) {
      setRejecting(false);
      setReason("");
      detail.reload();
      onChanged();
    }
  }

  const voiceBase = `/v1/outlets/${outletId}/staff/voice-orders/${orderId}`;
  return (
    <Sheet open={orderId !== null} onClose={onClose} variant="drawer" title={d ? `Order #${d.short_id}` : "Order"}>
      <ErrorBanner message={detail.error} />
      {!d && !detail.error ? <Skeleton what="order" lines={4} block /> : null}
      {d ? (
        <>
          <p className="inline">
            <Badge tone={statusView(d.status).tone}>{statusView(d.status).label}</Badge>
            <Badge tone={d.source === "voice" ? "info" : "neutral"}>{sourceLabel(d.source)}</Badge>
          </p>
          <p className="muted">Placed {timeOf(d.placed_at)}</p>

          <h3>Customer</h3>
          <dl className="facts">
            <div>
              <dt>Name</dt>
              <dd>{d.customer_name ?? "Not given"}</dd>
            </div>
            {d.customer_phone ? (
              <div>
                <dt>Phone</dt>
                <dd>
                  <a href={`tel:${d.customer_phone}`}>{d.customer_phone}</a>
                </dd>
              </div>
            ) : null}
            <div>
              <dt>Service</dt>
              <dd>
                {d.fulfillment_type === "delivery" ? "Delivery" : d.fulfillment_type === "pickup" ? "Pickup" : d.table_label ? `Dine in · Table ${d.table_label}` : "Dine in"}
              </dd>
            </div>
            {d.delivery_address ? (
              <div>
                <dt>Address</dt>
                <dd>{d.delivery_address}</dd>
              </div>
            ) : null}
          </dl>

          <h3>Items</h3>
          <ul className="plain">
            {d.lines.map((l, i) => (
              <li key={i} className={l.status === "cancelled" || l.void_reason ? "struck" : undefined}>
                <span className="line-row">
                  <span className="grow">
                    {l.qty} × {l.name}
                  </span>
                  <Money paise={l.line_total_paise} />
                </span>
                {l.modifiers.length > 0 ? <span className="muted">{l.modifiers.join(", ")}</span> : null}
                {l.notes ? <span className="muted">Note: {l.notes}</span> : null}
                {l.void_reason ? <span className="muted">Removed: {l.void_reason}</span> : null}
              </li>
            ))}
          </ul>

          <h3>Pricing</h3>
          <dl className="facts">
            <Price label="Items" paise={d.pricing.items_paise} />
            {d.pricing.cgst_paise > 0 ? <Price label={taxLabel("CGST", d.pricing.taxes_included)} paise={d.pricing.cgst_paise} /> : null}
            {d.pricing.sgst_paise > 0 ? <Price label={taxLabel("SGST", d.pricing.taxes_included)} paise={d.pricing.sgst_paise} /> : null}
            {d.pricing.liquor_vat_paise > 0 ? <Price label={taxLabel("Liquor VAT", d.pricing.taxes_included)} paise={d.pricing.liquor_vat_paise} /> : null}
            {d.pricing.service_charge_paise > 0 ? <Price label="Service charge" paise={d.pricing.service_charge_paise} /> : null}
            <Price label="Estimated total" paise={d.pricing.estimated_total_paise} strong />
          </dl>
          <p className="muted">
            An estimate for this order alone. The final bill is issued when the tab is closed.{" "}
            {d.tab_status === "closed" ? "The tab is closed." : d.tab_status === "bill_requested" ? "The bill has been requested." : "The tab is open."}
          </p>

          <h3>Timeline</h3>
          <ol className="timeline">
            {d.timeline.map((t, i) => (
              <li key={i}>
                <strong>{timeOf(t.at)}</strong> {t.label}
                {t.by ? <span className="muted"> · {t.by}</span> : null}
                {t.reason ? <span className="muted"> · {t.reason}</span> : null}
              </li>
            ))}
          </ol>
          {d.tickets.length > 0 ? (
            <p className="muted">
              {d.tickets.map((t) => ticketText(t.station, t.status)).join(" · ")}
            </p>
          ) : null}

          {rejecting ? (
            <Card>
              <Field label="Why are you rejecting it?" hint="This is saved with the order.">
                <input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} autoFocus />
              </Field>
              <div className="inline">
                <button
                  type="button"
                  className="danger-solid"
                  disabled={action.busy || reason.trim() === ""}
                  onClick={() => act(() => api(`${voiceBase}/reject`, { method: "POST", body: { reason: reason.trim() } }))}
                >
                  Reject order
                </button>
                <button type="button" className="secondary" disabled={action.busy} onClick={() => setRejecting(false)}>
                  Keep it
                </button>
              </div>
            </Card>
          ) : (
            <div className="inline">
              {d.actions.includes("accept") ? (
                <button type="button" disabled={action.busy} onClick={() => act(() => api(`${voiceBase}/accept`, { method: "POST" }))}>
                  Accept order
                </button>
              ) : null}
              {d.actions.includes("reject") ? (
                <button type="button" className="secondary" disabled={action.busy} onClick={() => setRejecting(true)}>
                  Reject…
                </button>
              ) : null}
              {d.actions.includes("serve") ? (
                <button
                  type="button"
                  disabled={action.busy}
                  onClick={() => act(() => api(`/v1/outlets/${outletId}/staff/tabs/${d.tab_id}/orders/${d.id}/serve`, { method: "POST", body: {} }))}
                >
                  Mark served
                </button>
              ) : null}
            </div>
          )}
        </>
      ) : null}
    </Sheet>
  );
}

function Price({ label, paise, strong }: { label: string; paise: number; strong?: boolean }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{strong ? <strong><Money paise={paise} /></strong> : <Money paise={paise} />}</dd>
    </div>
  );
}
