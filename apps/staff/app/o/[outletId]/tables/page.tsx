"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Badge, PageHeader, Skeleton } from "@restosaas/ui";
import { Card, ErrorBanner, Field } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api, openBlob } from "@/lib/api";
import { makeLabels } from "@/lib/labels";
import type { Table } from "@/lib/types";

export default function TablesPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}`;
  const tables = useResource<Table[]>(`${base}/tables`);
  const [zone, setZone] = useState("floor");
  const [prefix, setPrefix] = useState("T");
  const [count, setCount] = useState("10");
  const [seats, setSeats] = useState("4");
  const action = useAction();

  if (!tables.data) return tables.error ? <ErrorBanner message={tables.error} /> : <Skeleton what="your tables" lines={5} block />;
  const byZone = new Map<string, Table[]>();
  for (const t of tables.data) byZone.set(t.zone, [...(byZone.get(t.zone) ?? []), t]);

  async function add(event: FormEvent) {
    event.preventDefault();
    const n = Number(count);
    if (!Number.isInteger(n) || n < 1 || n > 200) return;
    if (await action.run(() => api(`${base}/tables/bulk`, { method: "POST", body: { zone, labels: makeLabels(prefix, n), seats: Number(seats) || 2 } }))) {
      tables.reload();
    }
  }

  return (
    <>
      <PageHeader
        title="Tables and QR codes"
        subtitle="Add tables, then print a QR code for each one. Guests scan it to order."
        actions={tables.data.length > 0 ? <button type="button" onClick={() => action.run(() => openBlob(`${base}/tables/qr-sheet.pdf`))}>Print all QR sheets</button> : undefined}
      />
      <Card title="Add tables">
        <form onSubmit={add}>
          <div className="row">
            <Field label="Zone" hint="Floor, terrace, bar…"><input required value={zone} onChange={(e) => setZone(e.target.value)} /></Field>
            <Field label="Label starts with"><input required value={prefix} onChange={(e) => setPrefix(e.target.value)} /></Field>
            <Field label="How many" size="short"><input inputMode="numeric" value={count} onChange={(e) => setCount(e.target.value)} /></Field>
            <Field label="Seats each" size="short"><input inputMode="numeric" value={seats} onChange={(e) => setSeats(e.target.value)} /></Field>
            <button type="submit" disabled={action.busy}>Add</button>
          </div>
          <p className="muted">Example: zone “bar”, label “B”, 6 makes B1 to B6. Counter seats are tables too.</p>
        </form>
      </Card>
      <ErrorBanner message={action.error} />
      {[...byZone.entries()].map(([zoneName, rows]) => (
        <Card key={zoneName} title={zoneName}>
          <div className="inline">
            <button type="button" className="secondary" onClick={() => action.run(() => openBlob(`${base}/tables/qr-sheet.pdf?zone=${encodeURIComponent(zoneName)}`))}>Print QR sheet (PDF)</button>
          </div>
          <table className="stacked">
            <thead><tr><th>Table</th><th>Seats</th><th>QR link</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  <td data-label="Table">{t.label} {!t.active ? <Badge tone="danger">Inactive</Badge> : null}</td>
                  <td data-label="Seats">{t.seats}</td>
                  <td data-label="QR link">{t.qr_url ? <a href={t.qr_url} target="_blank" rel="noreferrer">Open</a> : "—"}</td>
                  <td><div className="actions-cell">
                    <button type="button" className="secondary" onClick={() => { if (window.confirm(`Make a new QR for ${t.label}? Printed copies of the old one stop working.`)) action.run(async () => { await api(`${base}/tables/${t.id}/rotate-qr`, { method: "POST" }); tables.reload(); }); }}>New QR</button>
                    <button type="button" className="danger" onClick={() => action.run(async () => { await api(`${base}/tables/${t.id}`, { method: "DELETE" }); tables.reload(); })}>Delete</button>
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ))}
    </>
  );
}
