"use client";

import { useState } from "react";
import { formatInr } from "@restosaas/ui";
import { Card, ErrorBanner } from "@/components/ui";
import { useAction } from "@/components/hooks";
import { api, openBlob } from "@/lib/api";
import type { ImportPreview } from "@/lib/types";

export function MenuImport({ base, reload }: { base: string; reload: () => void }) {
  const [csv, setCsv] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const action = useAction();

  async function choose(file: File | undefined) {
    setPreview(null);
    setDone(null);
    if (!file) return;
    const text = await file.text();
    setCsv(text);
    await action.run(async () => {
      setPreview(await api<ImportPreview>(`${base}/menu/import/preview`, { method: "POST", raw: text }));
    });
  }

  async function apply() {
    if (!csv || !preview?.diff_hash) return;
    const hash = preview.diff_hash;
    const ok = await action.run(async () => {
      const r = await api<{ categories_added: number; items_added: number; items_updated: number }>(
        `${base}/menu/import/apply?diff_hash=${hash}`, { method: "POST", raw: csv },
      );
      setDone(`Added ${r.items_added} items and ${r.categories_added} categories; updated ${r.items_updated}.`);
    });
    if (ok) { setPreview(null); setCsv(null); reload(); }
  }

  return (
    <Card title="Import from CSV">
      <p className="muted">
        Download the current menu as a spreadsheet, edit it, and upload it. You will see exactly what changes before anything is saved.
        Items that are not in the file are never deleted.
      </p>
      <div className="inline">
        <button type="button" className="secondary" onClick={() => action.run(() => openBlob(`${base}/menu/export.csv`, "menu.csv"))}>Download menu.csv</button>
        <label className="button secondary">
          Choose a CSV file
          <input type="file" accept=".csv,text/csv" hidden onChange={(e) => choose(e.target.files?.[0])} />
        </label>
      </div>
      <ErrorBanner message={action.error} />
      {done ? <p role="status" className="ok">{done}</p> : null}

      {preview && preview.errors.length > 0 ? (
        <>
          <h3>Fix these first</h3>
          <table>
            <thead><tr><th>Row</th><th>Column</th><th>Problem</th></tr></thead>
            <tbody>{preview.errors.map((e, i) => <tr key={i}><td>{e.row}</td><td>{e.column ?? ""}</td><td>{e.message}</td></tr>)}</tbody>
          </table>
        </>
      ) : null}

      {preview && preview.diff_hash ? (
        <>
          <h3>Preview</h3>
          <ul>
            <li>{preview.added.length} new items{preview.new_categories.length ? `, ${preview.new_categories.length} new categories (${preview.new_categories.join(", ")})` : ""}</li>
            <li>{preview.changed.length} changed items</li>
            <li>{preview.unchanged} unchanged</li>
            <li>{preview.not_in_file.length} on your menu but not in the file (kept as they are)</li>
          </ul>
          {preview.added.length ? (
            <table><thead><tr><th>New item</th><th>Category</th><th>Price</th></tr></thead>
              <tbody>{preview.added.map((a) => <tr key={`${a.category}/${a.item}`}><td>{a.item}</td><td>{a.category}</td><td>{formatInr(a.price_paise)}</td></tr>)}</tbody></table>
          ) : null}
          {preview.changed.length ? (
            <table><thead><tr><th>Changed item</th><th>What changes</th></tr></thead>
              <tbody>{preview.changed.map((c) => (
                <tr key={`${c.category}/${c.item}`}><td>{c.item}</td><td>{Object.entries(c.changes).map(([field, [from, to]]) => (
                  <div key={field}>{field === "price_paise" ? `price ${formatInr(from as number)} → ${formatInr(to as number)}` : `${field}: ${JSON.stringify(from)} → ${JSON.stringify(to)}`}</div>
                ))}</td></tr>
              ))}</tbody></table>
          ) : null}
          <button type="button" disabled={action.busy || (preview.added.length + preview.changed.length === 0)} onClick={apply}>Apply changes</button>
        </>
      ) : null}
    </Card>
  );
}
