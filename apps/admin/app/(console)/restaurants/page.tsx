"use client";

import { useMemo, useState } from "react";
import { Badge, EmptyState, ErrorBanner, Field, PageHeader, Sheet, Skeleton } from "@restosaas/ui";
import { api } from "@/lib/api";
import { countByStatus, filterRestaurants, formatDay, initialOf, type StatusFilter } from "@/lib/restaurants";
import type { PlatformRestaurant } from "@/lib/types";
import { useAction, useResource } from "@/lib/use-resource";
import { VoiceSheet } from "./voice-sheet";

const FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "suspended", label: "Suspended" },
];

export default function RestaurantsPage() {
  const list = useResource<PlatformRestaurant[]>("/v1/platform/restaurants");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [target, setTarget] = useState<PlatformRestaurant | null>(null);
  const [reason, setReason] = useState("");
  const [voiceFor, setVoiceFor] = useState<PlatformRestaurant | null>(null);
  const action = useAction();

  const shown = useMemo(() => filterRestaurants(list.data ?? [], query, status), [list.data, query, status]);
  const counts = useMemo(() => countByStatus(list.data ?? []), [list.data]);

  if (!list.data) {
    return (
      <>
        <PageHeader title="Restaurants" />
        {list.error ? <ErrorBanner message={list.error} /> : <Skeleton what="restaurants" lines={3} block />}
      </>
    );
  }

  const suspending = target?.status === "active";

  async function confirm() {
    if (!target) return;
    const done = await action.run(() =>
      api(`/v1/platform/restaurants/${target.id}/status`, {
        method: "PUT",
        body: { status: suspending ? "suspended" : "active", reason: suspending ? reason : null },
      }),
    );
    if (done) {
      setTarget(null);
      setReason("");
      list.reload();
    }
  }

  function close() {
    setTarget(null);
    setReason("");
    action.clearError();
  }

  return (
    <>
      <PageHeader title="Restaurants" subtitle={`${counts.all} on the platform · ${counts.active} active · ${counts.suspended} suspended`} />
      <ErrorBanner message={list.error} />
      <div className="toolbar">
        <Field label="Search restaurants">
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Restaurant or registered name" />
        </Field>
        <div className="chips" role="group" aria-label="Status">
          {FILTERS.map((f) => (
            <button key={f.value} type="button" aria-pressed={status === f.value} onClick={() => setStatus(f.value)}>
              {f.label} <span className="count">{counts[f.value]}</span>
            </button>
          ))}
        </div>
      </div>

      {shown.length === 0 ? (
        <EmptyState
          title={counts.all === 0 ? "No restaurants yet" : "No restaurants match"}
          action={
            counts.all > 0 ? (
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setQuery("");
                  setStatus("all");
                }}
              >
                Clear filters
              </button>
            ) : undefined
          }
        >
          {counts.all === 0 ? "Restaurants appear here when they sign up." : "Try a different name, or show every status."}
        </EmptyState>
      ) : (
        <ul className="restaurant-grid">
          {shown.map((r) => (
            <li key={r.id} className="restaurant-card">
              <div className="top">
                <span className="avatar" aria-hidden="true">
                  {initialOf(r.brand_name)}
                </span>
                <div className="names">
                  <h2>{r.brand_name}</h2>
                  <span>{r.legal_name}</span>
                </div>
              </div>
              <div className="meta">
                <Badge tone={r.status === "active" ? "ok" : "danger"}>{r.status === "active" ? "Active" : "Suspended"}</Badge>
                <Badge>Plan: {r.plan}</Badge>
                <Badge tone={r.voice_orders_allowed ? "ok" : "neutral"}>Voice orders: {r.voice_orders_allowed ? "enabled" : "disabled"}</Badge>
                <span className="since">Joined {formatDay(r.created_at)}</span>
              </div>
              <button type="button" className="secondary" aria-label={`Voice orders for ${r.brand_name}`} onClick={() => setVoiceFor(r)}>
                Voice orders
              </button>
              <button
                type="button"
                className={r.status === "active" ? "danger" : "secondary"}
                aria-label={`${r.status === "active" ? "Suspend" : "Reactivate"} ${r.brand_name}`}
                onClick={() => setTarget(r)}
              >
                {r.status === "active" ? "Suspend" : "Reactivate"}
              </button>
            </li>
          ))}
        </ul>
      )}

      <VoiceSheet restaurant={voiceFor} onClose={() => setVoiceFor(null)} onChanged={list.reload} />

      <Sheet open={target !== null} onClose={close} title={target ? `${suspending ? "Suspend" : "Reactivate"} ${target.brand_name}?` : ""}>
        {target ? (
          <>
            <p className="muted">
              {suspending
                ? "Staff and guests are turned away on their next request. Nothing is deleted, and you can reactivate at any time."
                : "Staff and guests can use the restaurant again straight away."}
            </p>
            {suspending ? (
              <Field label="Reason" hint="Recorded in the audit log, with your name.">
                <textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} />
              </Field>
            ) : null}
            <ErrorBanner message={action.error} />
            <div className="stack">
              <button
                type="button"
                className={suspending ? "danger-solid btn-lg" : "btn-lg"}
                disabled={action.busy || (suspending && reason.trim().length < 3)}
                onClick={confirm}
              >
                {suspending ? "Suspend restaurant" : "Reactivate restaurant"}
              </button>
              <button type="button" className="secondary btn-lg" onClick={close}>
                Cancel
              </button>
            </div>
          </>
        ) : null}
      </Sheet>
    </>
  );
}
