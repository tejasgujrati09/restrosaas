"use client";

import { useEffect, useState } from "react";
import { Badge, EmptyState, ErrorBanner, PageHeader, Skeleton } from "@restosaas/ui";
import { api, errorMessage } from "@/lib/api";
import { actionLabel, actorLabel, formatWhen, reasonOf } from "@/lib/restaurants";
import type { AuditEntry } from "@/lib/types";

const PAGE = 50;

type Scope = "platform" | "all";
const SCOPES: { value: Scope; label: string; prefix: string }[] = [
  { value: "platform", label: "Platform actions", prefix: "restaurant." },
  { value: "all", label: "All activity", prefix: "" },
];

export default function AuditPage() {
  const [scope, setScope] = useState<Scope>("platform");
  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="What the platform did to restaurants, and (with All activity) every change staff made. Newest first."
      />
      <div className="chips" role="group" aria-label="Show">
        {SCOPES.map((s) => (
          <button key={s.value} type="button" aria-pressed={scope === s.value} onClick={() => setScope(s.value)}>
            {s.label}
          </button>
        ))}
      </div>
      {/* Keyed by scope: switching starts a fresh load instead of patching state in an effect. */}
      <AuditTable key={scope} prefix={SCOPES.find((s) => s.value === scope)?.prefix ?? ""} />
    </>
  );
}

function AuditTable({ prefix }: { prefix: string }) {
  const [rows, setRows] = useState<AuditEntry[] | null>(null);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const query = `limit=${PAGE}${prefix ? `&action_prefix=${encodeURIComponent(prefix)}` : ""}`;

  useEffect(() => {
    api<AuditEntry[]>(`/v1/platform/audit-log?${query}`)
      .then((first) => {
        setRows(first);
        setMore(first.length === PAGE);
      })
      .catch((e: unknown) => setError(errorMessage(e)));
  }, [query]);

  async function older() {
    const last = rows?.[rows.length - 1];
    if (!last) return;
    setLoadingMore(true);
    try {
      const next = await api<AuditEntry[]>(`/v1/platform/audit-log?${query}&before=${encodeURIComponent(last.at)}`);
      setRows([...(rows ?? []), ...next]);
      setMore(next.length === PAGE);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoadingMore(false);
    }
  }

  if (!rows) return error ? <ErrorBanner message={error} /> : <Skeleton what="the audit log" lines={5} />;

  return (
    <>
      <ErrorBanner message={error} />
      {rows.length === 0 ? (
        <EmptyState title="Nothing has happened yet">Suspensions, reactivations and other changes are recorded here.</EmptyState>
      ) : (
        <table className="stacked audit">
          <thead>
            <tr>
              <th>When</th>
              <th>Who</th>
              <th>What</th>
              <th>Restaurant</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => {
              const reason = reasonOf(e);
              return (
                <tr key={e.id}>
                  <td data-label="When">{formatWhen(e.at)}</td>
                  <td data-label="Who">{actorLabel(e)}</td>
                  <td data-label="What">
                    <Badge tone={e.action.endsWith("suspended") ? "danger" : e.action.endsWith("reactivated") ? "ok" : "neutral"}>
                      {actionLabel(e.action)}
                    </Badge>
                  </td>
                  <td data-label="Restaurant">{e.restaurant_name ?? "—"}</td>
                  <td data-label="Reason">{reason ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {more ? (
        <button type="button" className="secondary" disabled={loadingMore} aria-busy={loadingMore} onClick={older}>
          Load older
        </button>
      ) : null}
    </>
  );
}
