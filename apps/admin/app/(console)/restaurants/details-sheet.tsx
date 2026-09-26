"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Badge, ErrorBanner, Field, Notice, Sheet, Skeleton, sentenceCase, stateName, toast } from "@restosaas/ui";
import { api } from "@/lib/api";
import { agoLabel, expiryLabel, expiryTone, formatDay, formatPhone, formatWhen } from "@/lib/restaurants";
import type { PlatformRestaurant, PlatformRestaurantDetail } from "@/lib/types";
import { useAction, useResource } from "@/lib/use-resource";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="detail-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="detail-section">
      <h3>{title}</h3>
      <dl className="detail-list">{children}</dl>
    </section>
  );
}

const ROLE_ORDER = ["owner", "manager", "waiter", "kitchen", "bar"];

/** Everything about one restaurant in one place: who they are, their plan and when it ends,
 *  where they are, who runs it, how big it is and how much it is used. Counts and contacts only;
 *  never orders, guests or prices. */
export function DetailsSheet({
  restaurant,
  onClose,
  onSuspend,
  onVoice,
  onChanged,
}: {
  restaurant: PlatformRestaurant | null;
  onClose: () => void;
  onSuspend: (r: PlatformRestaurant) => void;
  onVoice: (r: PlatformRestaurant) => void;
  onChanged: () => void;
}) {
  const path = restaurant ? `/v1/platform/restaurants/${restaurant.id}` : null;
  const detail = useResource<PlatformRestaurantDetail>(path);
  const [expiry, setExpiry] = useState("");
  const action = useAction();
  const d = detail.data;
  const r = restaurant;

  // Show what is saved, in the date field, whenever the details load or change.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setExpiry(d?.plan_expires_at ? d.plan_expires_at.slice(0, 10) : "");
  }, [d?.plan_expires_at]);

  async function saveExpiry(value: string | null) {
    if (!path) return;
    const ok = await action.run(() => api(`${path}/plan-expiry`, { method: "PUT", body: { expires_on: value } }));
    if (ok) {
      toast.ok(value ? "Plan expiry saved." : "Plan expiry cleared.");
      detail.reload();
      onChanged();
    }
  }

  return (
    <Sheet open={r !== null} onClose={onClose} title={r?.brand_name ?? ""}>
      {r ? (
        <>
          <div className="detail-badges">
            <Badge tone={r.status === "active" ? "ok" : "danger"}>{r.status === "active" ? "Active" : "Suspended"}</Badge>
            <Badge>Plan: {sentenceCase(r.plan)}</Badge>
            <Badge tone={r.voice_orders_allowed ? "ok" : "neutral"}>Voice orders: {r.voice_orders_allowed ? "enabled" : "disabled"}</Badge>
          </div>
          {!d ? (
            detail.error ? <ErrorBanner message={detail.error} onRetry={detail.reload} /> : <Skeleton what="the restaurant's details" lines={6} block />
          ) : (
            <>
              {d.suspension ? (
                <Notice>
                  Suspended {formatWhen(d.suspension.at)}{d.suspension.by_name ? ` by ${d.suspension.by_name}` : ""}
                  {d.suspension.reason ? `: “${d.suspension.reason}”` : "."}
                </Notice>
              ) : null}

              <Section title="Business">
                <Row label="Registered name">{d.legal_name}</Row>
                <Row label="GSTIN">{d.gstin ?? <span className="muted">Not provided</span>}</Row>
                <Row label="Joined">{formatDay(d.created_at)} <span className="muted">({agoLabel(d.created_at)})</span></Row>
                <Row label="Restaurant ID"><code>{d.id}</code></Row>
              </Section>

              <section className="detail-section">
                <h3>Plan</h3>
                <dl className="detail-list">
                  <Row label="Plan">{sentenceCase(d.plan)}</Row>
                  <Row label="Plan ends">
                    {d.plan_expires_at ? formatDay(d.plan_expires_at) : <span className="muted">No expiry set</span>}{" "}
                    <Badge tone={expiryTone(d.days_until_expiry)}>{d.days_until_expiry === null ? "Open-ended" : d.days_until_expiry < 0 ? `Ended ${expiryLabel(d.days_until_expiry)}` : `Ends ${expiryLabel(d.days_until_expiry)}`}</Badge>
                  </Row>
                </dl>
                <div className="detail-expiry">
                  <Field label="Set the last day of the plan">
                    <input type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} />
                  </Field>
                  <button type="button" disabled={action.busy || expiry === ""} onClick={() => saveExpiry(expiry)}>Save date</button>
                  {d.plan_expires_at ? <button type="button" className="tertiary" disabled={action.busy} onClick={() => saveExpiry(null)}>Clear</button> : null}
                </div>
              </section>

              <section className="detail-section">
                <h3>{d.outlets.length === 1 ? "Outlet" : "Outlets"}</h3>
                {d.outlets.length === 0 ? <p className="muted">No outlet has been set up yet.</p> : null}
                {d.outlets.map((o) => (
                  <dl key={o.id} className="detail-list outlet">
                    <Row label="Name">{o.name}</Row>
                    <Row label="Address">{o.address ?? <span className="muted">Not provided</span>}</Row>
                    <Row label="State">{stateName(o.state_code)} <span className="muted">(GST code {o.state_code})</span></Row>
                    <Row label="Time zone">{o.timezone}</Row>
                    <Row label="Tables">{o.tables}</Row>
                    <Row label="Liquor">{o.liquor_licensed ? "Licensed" : "Not licensed"}</Row>
                  </dl>
                ))}
              </section>

              <Section title="Owner">
                {d.owners.length === 0 ? <Row label="Contact"><span className="muted">No active owner</span></Row> : null}
                {d.owners.map((o) => (
                  <Row key={o.phone} label={o.name ?? "Owner"}><a href={`tel:${o.phone}`}>{formatPhone(o.phone)}</a></Row>
                ))}
              </Section>

              <Section title="Team and menu">
                <Row label="Active staff">
                  {Object.keys(d.staff_by_role).length === 0
                    ? <span className="muted">None</span>
                    : [...ROLE_ORDER, ...Object.keys(d.staff_by_role).filter((k) => !ROLE_ORDER.includes(k))]
                        .filter((k) => d.staff_by_role[k])
                        .map((k) => `${d.staff_by_role[k]} ${k}`)
                        .join(" · ")}
                </Row>
                <Row label="Menu">{d.menu_items} items in {d.menu_categories} categories</Row>
                <Row label="Tax classes">{d.tax_classes}</Row>
              </Section>

              <Section title="Activity">
                <Row label="Rounds placed">{d.activity.orders_total} in total · {d.activity.orders_30d} in 30 days · {d.activity.orders_7d} in 7 days</Row>
                <Row label="Open tabs now">{d.activity.open_tabs}</Row>
                <Row label="First round">{d.activity.first_order_at ? formatDay(d.activity.first_order_at) : <span className="muted">None yet</span>}</Row>
                <Row label="Last round">{d.activity.last_order_at ? <>{formatWhen(d.activity.last_order_at)} <span className="muted">({agoLabel(d.activity.last_order_at)})</span></> : <span className="muted">None yet</span>}</Row>
              </Section>

              <div className="detail-actions">
                <button type="button" className="secondary" onClick={() => { onClose(); onVoice(r); }}>Voice orders</button>
                <button type="button" className={r.status === "active" ? "danger" : "secondary"} onClick={() => { onClose(); onSuspend(r); }}>
                  {r.status === "active" ? "Suspend" : "Reactivate"}
                </button>
              </div>
            </>
          )}
        </>
      ) : null}
    </Sheet>
  );
}
