"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Badge, PageHeader, sentenceCase, Skeleton } from "@restosaas/ui";
import { ErrorBanner, Field } from "@/components/ui";
import { AddTable } from "@/components/add-table";
import { useAction, useResource } from "@/components/hooks";
import { api, openBlob } from "@/lib/api";
import { nextLabel, placeholderCount, plural } from "@/lib/assign";
import { makeLabels } from "@/lib/labels";
import type { Table } from "@/lib/types";

/** Every table as a card with its QR actions. New tables are added in the "+ Add table" slots;
 *  the form there, and the "several at once" form, always start blank. */
export default function TablesPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}`;
  const tables = useResource<Table[]>(`${base}/tables`);
  const [adding, setAdding] = useState<{ zone: string; key: number } | null>(null);
  const [zone, setZone] = useState("");
  const [prefix, setPrefix] = useState("");
  const [count, setCount] = useState("");
  const [seats, setSeats] = useState("");
  const action = useAction();

  if (!tables.data) return tables.error ? <ErrorBanner message={tables.error} onRetry={tables.reload} /> : <Skeleton what="your tables" lines={5} block />;
  const byZone = new Map<string, Table[]>();
  for (const t of tables.data) byZone.set(t.zone, [...(byZone.get(t.zone) ?? []), t]);
  if (byZone.size === 0) byZone.set("", []);
  const all = tables.data;
  const labels = all.map((t) => t.label);

  async function addSeveral(event: FormEvent) {
    event.preventDefault();
    const n = Number(count);
    if (!Number.isInteger(n) || n < 1 || n > 200) return;
    const ok = await action.run(() =>
      api(`${base}/tables/bulk`, { method: "POST", body: { zone: zone.trim() || "floor", labels: makeLabels(prefix.trim() || "T", n), seats: Number(seats) || 2 } }),
    );
    if (ok) {
      setZone(""); setPrefix(""); setCount(""); setSeats("");
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
      <section className="card add-zone" aria-label="Add a zone or several tables">
        <h2>Add a zone</h2>
        <form onSubmit={addSeveral}>
          <div className="row">
            <Field label="Zone"><input value={zone} placeholder="e.g. Bar, Terrace" onChange={(e) => setZone(e.target.value)} /></Field>
            <Field label="Label starts with"><input value={prefix} placeholder="e.g. B" onChange={(e) => setPrefix(e.target.value)} /></Field>
            <Field label="How many" size="short"><input required inputMode="numeric" value={count} placeholder="6" onChange={(e) => setCount(e.target.value)} /></Field>
            <Field label="Seats each" size="short"><input inputMode="numeric" value={seats} placeholder="2" onChange={(e) => setSeats(e.target.value)} /></Field>
            <button type="submit" disabled={action.busy}>Add</button>
          </div>
          <p className="muted">Example: zone “bar”, label “B”, 6 makes B1 to B6. Counter seats are tables too. Empty boxes use floor, T and 2 seats. To add one table, use a “+ Add table” card below.</p>
        </form>
      </section>
      {[...byZone.entries()].map(([zoneName, rows]) => (
        <section key={zoneName || "new"} aria-label={zoneName || "New tables"}>
          <div className="zone-head">
            <h2 className="zone">{zoneName ? sentenceCase(zoneName) : "Your tables"}</h2>
            {rows.length > 0 ? (
              <button type="button" className="secondary" onClick={() => action.run(() => openBlob(`${base}/tables/qr-sheet.pdf?zone=${encodeURIComponent(zoneName)}`))}>Print QR sheet (PDF)</button>
            ) : null}
          </div>
          <div className="tiles roomy">
            {rows.map((t) => (
              <article key={t.id} className="tile static" aria-label={`Table ${t.label}`}>
                <span className="tile-head">
                  <span className="tile-name">{t.label}</span>
                  {!t.active ? <Badge tone="danger">Inactive</Badge> : null}
                </span>
                <span className="muted">{plural(t.seats, "seat")}</span>
                {t.qr_url ? <a href={t.qr_url} target="_blank" rel="noreferrer">Open QR link</a> : null}
                <span className="tile-foot">
                  <button type="button" onClick={() => { if (window.confirm(`Make a new QR for ${t.label}? Printed copies of the old one stop working.`)) action.run(async () => { await api(`${base}/tables/${t.id}/rotate-qr`, { method: "POST" }); tables.reload(); }); }}>New QR</button>
                  <button type="button" onClick={() => action.run(async () => { await api(`${base}/tables/${t.id}`, { method: "DELETE" }); tables.reload(); })}>Delete</button>
                </span>
              </article>
            ))}
            {Array.from({ length: placeholderCount(all.length) }, (_, i) =>
              adding && adding.zone === zoneName && i === 0 ? (
                <AddTable
                  key={`add-${adding.key}`}
                  base={base}
                  zone={zoneName || undefined}
                  suggestion={nextLabel(labels)}
                  onDone={() => { setAdding(null); tables.reload(); }}
                  onCancel={() => setAdding(null)}
                />
              ) : (
                <button key={`slot-${i}`} type="button" className="tile placeholder" onClick={() => setAdding({ zone: zoneName, key: Date.now() })}>
                  <span className="plus" aria-hidden="true">+</span> Add table
                </button>
              ),
            )}
          </div>
        </section>
      ))}
    </>
  );
}
