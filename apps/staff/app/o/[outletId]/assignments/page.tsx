"use client";

import { useParams } from "next/navigation";
import { EmptyState, PageHeader, sentenceCase, Skeleton } from "@restosaas/ui";
import { ErrorBanner } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import type { Staff, TableAssignment } from "@/lib/types";

/** Who serves which table. Waiters see only their own tables, so an unassigned table is
 * a manager's to look after. */
export default function AssignmentsPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}`;
  const rows = useResource<TableAssignment[]>(`${base}/table-assignments`);
  const staff = useResource<Staff[]>(`${base}/staff`);
  const action = useAction();

  if (!rows.data || !staff.data) return rows.error ?? staff.error ? <ErrorBanner message={rows.error ?? staff.error} /> : <Skeleton what="table assignments" lines={4} block />;
  const waiters = staff.data.filter((s) => s.role === "waiter" && s.active);
  const zones = new Map<string, TableAssignment[]>();
  for (const r of rows.data) zones.set(r.zone, [...(zones.get(r.zone) ?? []), r]);

  const has = (r: TableAssignment, userId: string) => r.waiters.some((w) => w.user_id === userId);

  async function toggleTable(r: TableAssignment, userId: string) {
    const current = r.waiters.map((w) => w.user_id);
    const next = current.includes(userId) ? current.filter((u) => u !== userId) : [...current, userId];
    if (await action.run(() => api(`${base}/tables/${r.table_id}/assignees`, { method: "PUT", body: { user_ids: next } }))) rows.reload();
  }

  async function toggleZone(zone: string, list: TableAssignment[], userId: string) {
    const everyone = new Set<string>();
    for (const r of list) for (const w of r.waiters) everyone.add(w.user_id);
    const allHave = list.every((r) => has(r, userId));
    if (allHave) everyone.delete(userId);
    else everyone.add(userId);
    // Setting a zone replaces each table's waiters with this set, so keep the ones only some tables had.
    if (await action.run(() => api(`${base}/table-assignments/zone`, { method: "PUT", body: { zone, user_ids: [...everyone] } }))) rows.reload();
  }

  return (
    <>
      <PageHeader title="Assign tables" subtitle="A waiter sees and takes orders for the tables ticked here. Managers and owners always see every table." />
      <ErrorBanner message={action.error ?? rows.error} />
      {waiters.length === 0 ? <EmptyState title="There are no active waiters yet">Invite some under Staff, then tick the tables they serve here.</EmptyState> : null}
      {[...zones.entries()].map(([zone, list]) => (
        <section key={zone} className="card" aria-label={zone}>
          <h2>{sentenceCase(zone)}</h2>
          <div className="scroll-x">
          <table className="matrix">
            <thead>
              <tr>
                <th>Table</th>
                {waiters.map((w) => (
                  <th key={w.user_id}>{w.name ?? w.phone}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Whole zone</strong></td>
                {waiters.map((w) => (
                  <td key={w.user_id}>
                    <input type="checkbox" aria-label={`${w.name ?? w.phone} for the whole ${zone} zone`} checked={list.every((r) => has(r, w.user_id))} disabled={action.busy} onChange={() => toggleZone(zone, list, w.user_id)} />
                  </td>
                ))}
              </tr>
              {list.map((r) => (
                <tr key={r.table_id}>
                  <td>{r.label}</td>
                  {waiters.map((w) => (
                    <td key={w.user_id}>
                      <input type="checkbox" aria-label={`${w.name ?? w.phone} for table ${r.label}`} checked={has(r, w.user_id)} disabled={action.busy} onChange={() => toggleTable(r, w.user_id)} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </section>
      ))}
    </>
  );
}
