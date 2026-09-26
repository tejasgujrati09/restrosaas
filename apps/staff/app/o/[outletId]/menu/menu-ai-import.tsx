"use client";

import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { Badge, EmptyState, formatInr, Skeleton, toast } from "@restosaas/ui";
import { Card, Field } from "@/components/ui";
import { useAction } from "@/components/hooks";
import { api, openBlob, uploadFiles } from "@/lib/api";
import { ACCEPT, addFiles, formatSize, MAX_FILES, move } from "@/lib/menu-files";
import type { MenuImportDefaults, MenuImportJob, MenuImportReview, MenuImportRow } from "@/lib/types";

type Phase = "pick" | "uploading" | "working" | "failed" | "review" | "done";

const POLL_MS = 1500;

function storedId(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function keepId(key: string, id: string | null) {
  try {
    if (id) window.localStorage.setItem(key, id);
    else window.localStorage.removeItem(key);
  } catch {
    // storage blocked: the import still works, it just cannot be resumed after a reload
  }
}

/** Import a menu from a PDF or photos. The server reads it in the background; nothing reaches
 *  the live menu until the owner reviews the rows and confirms. */
export function MenuAiImport({ base, reload }: { base: string; reload: () => void }) {
  const storeKey = `menu-import:${base}`;
  const [phase, setPhase] = useState<Phase>("pick");
  const [files, setFiles] = useState<File[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [progress, setProgress] = useState(0);
  const [job, setJob] = useState<MenuImportJob | null>(null);
  const [review, setReview] = useState<MenuImportReview | null>(null);
  const [rows, setRows] = useState<MenuImportRow[]>([]);
  const [defaults, setDefaults] = useState<MenuImportDefaults>({});
  const [dirty, setDirty] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [resuming, setResuming] = useState(true);
  const action = useAction();
  const uploadKey = useRef<string | null>(null);
  const confirmKey = useRef<string | null>(null);
  const jobPath = job ? `${base}/menu/imports/${job.id}` : null;

  const showReview = useCallback((data: MenuImportReview) => {
    setReview(data);
    setRows(data.rows);
    setDefaults(data.defaults);
    setDirty(false);
    setPhase("review");
  }, []);

  const applyJob = useCallback(
    async (current: MenuImportJob) => {
      setJob(current);
      if (current.status === "ready") {
        showReview(await api<MenuImportReview>(`${base}/menu/imports/${current.id}/preview`));
      } else if (current.status === "failed") setPhase("failed");
      else if (current.status === "applied") { keepId(storeKey, null); setPhase("pick"); }
      else setPhase("working");
    },
    [base, showReview, storeKey],
  );

  const follow = useCallback(
    (id: string) => api<MenuImportJob>(`${base}/menu/imports/${id}`).then(applyJob),
    [base, applyJob],
  );

  // Pick up an import that was in progress before a reload.
  useEffect(() => {
    const id = storedId(storeKey);
    const resumed = id
      ? api<MenuImportJob>(`${base}/menu/imports/${id}`).then(applyJob).catch(() => keepId(storeKey, null))
      : Promise.resolve();
    void resumed.finally(() => setResuming(false));
  }, [base, applyJob, storeKey]);

  // While the server is working, ask how far it has got.
  useEffect(() => {
    if (phase !== "working" || !job) return;
    const timer = window.setInterval(() => {
      follow(job.id).catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [phase, job, follow]);

  function choose(list: FileList | File[] | null) {
    if (!list) return;
    const result = addFiles(files, Array.from(list));
    setFiles(result.files);
    setProblems(result.problems);
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files);
  }

  async function start() {
    uploadKey.current ??= crypto.randomUUID();
    setPhase("uploading");
    setProgress(0);
    const ok = await action.run(async () => {
      const created = await uploadFiles<MenuImportJob>(`${base}/menu/imports`, files, setProgress, uploadKey.current!);
      keepId(storeKey, created.id);
      setJob(created);
      setPhase("working");
    });
    if (!ok) setPhase("pick");
  }

  function reset() {
    keepId(storeKey, null);
    uploadKey.current = null;
    confirmKey.current = null;
    setFiles([]); setProblems([]); setJob(null); setReview(null); setRows([]); setDirty(false);
    setPhase("pick");
  }

  async function retry() {
    if (!jobPath) return;
    const ok = await action.run(async () => setJob(await api<MenuImportJob>(`${jobPath}/retry`, { method: "POST" })));
    if (ok) setPhase("working");
  }

  async function save() {
    if (!jobPath) return;
    await action.run(async () => {
      showReview(await api<MenuImportReview>(jobPath, { method: "PUT", body: { rows, defaults } }));
      confirmKey.current = null;
    });
  }

  async function confirm() {
    const hash = review?.diff?.diff_hash;
    if (!jobPath || !hash) return;
    confirmKey.current ??= crypto.randomUUID();
    const ok = await action.run(async () => {
      const r = await api<{ categories_added: number; items_added: number; items_updated: number }>(
        `${jobPath}/confirm?diff_hash=${hash}`, { method: "POST", idempotencyKey: confirmKey.current! },
      );
      toast.ok(`Added ${r.items_added} items and ${r.categories_added} categories; updated ${r.items_updated}.`);
    });
    if (ok) { reset(); setPhase("done"); reload(); }
  }

  function edit(index: number, patch: Partial<MenuImportRow>) {
    setRows((current) => current.map((r, i) => (i === index ? { ...r, ...patch } : r)));
    setDirty(true);
  }

  if (resuming) {
    return <Card title="Import from a PDF or photos"><Skeleton what="your import" lines={2} /></Card>;
  }

  return (
    <Card title="Import from a PDF or photos">

      {phase === "pick" || phase === "uploading" || phase === "done" ? (
        <>
          <p className="muted">
            Upload your existing menu as a PDF or as photos, in page order. We read it for you, then you check every row before anything is saved.
          </p>
          <label
            className={dragging ? "filedrop dragging" : "filedrop"}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <span className="filedrop-title">Drag files here, or choose files</span>
            <span className="muted">PDF, JPG or PNG. Up to {MAX_FILES} files, {formatSize(15_000_000)} each.</span>
            <input type="file" accept={ACCEPT} multiple disabled={phase === "uploading"}
              onChange={(e) => { choose(e.target.files); e.target.value = ""; }} />
          </label>
          {problems.length ? <ul className="error" role="alert">{problems.map((p) => <li key={p}>{p}</li>)}</ul> : null}
          {files.length === 0 ? null : (
            <>
              <ol className="filelist" aria-label="Files, in reading order">
                {files.map((f, i) => (
                  <li key={`${f.name}-${i}`}>
                    <span>{i + 1}. {f.name} <span className="muted">({formatSize(f.size)})</span></span>
                    <span className="inline">
                      <button type="button" className="tertiary" aria-label={`Move ${f.name} up`} disabled={i === 0 || phase === "uploading"} onClick={() => setFiles(move(files, i, i - 1))}>↑</button>
                      <button type="button" className="tertiary" aria-label={`Move ${f.name} down`} disabled={i === files.length - 1 || phase === "uploading"} onClick={() => setFiles(move(files, i, i + 1))}>↓</button>
                      <button type="button" className="tertiary" aria-label={`Remove ${f.name}`} disabled={phase === "uploading"} onClick={() => { setFiles(files.filter((_, j) => j !== i)); uploadKey.current = null; }}>Remove</button>
                    </span>
                  </li>
                ))}
              </ol>
              {phase === "uploading" ? (
                <p role="status">Uploading… <progress max={1} value={progress} aria-label="Upload progress" /> {Math.round(progress * 100)}%</p>
              ) : null}
              <button type="button" disabled={action.busy || phase === "uploading"} onClick={start}>Read menu</button>
            </>
          )}
        </>
      ) : null}

      {phase === "working" && job ? (
        <div role="status" aria-live="polite">
          <p>{job.stage ?? "Working"}{job.pages_total ? ` (${job.pages_done} of ${job.pages_total} pages done)` : ""}</p>
          <progress max={Math.max(job.pages_total, 1)} value={job.pages_done} aria-label="Reading progress" />
          <p className="muted">You can leave this page; we keep going and it will be here when you come back.</p>
        </div>
      ) : null}

      {phase === "failed" && job ? (
        <>
          <p className="error" role="alert">{job.error ?? "Could not read the menu."}</p>
          <div className="inline">
            <button type="button" disabled={action.busy} onClick={retry}>Try again</button>
            <button type="button" className="secondary" onClick={reset}>Start over</button>
          </div>
        </>
      ) : null}

      {phase === "review" && review ? (
        <Review
          review={review} rows={rows} defaults={defaults} dirty={dirty} busy={action.busy}
          onEdit={edit} onDefaults={(d) => { setDefaults(d); setDirty(true); }}
          onSave={save} onConfirm={confirm} onCancel={reset}
          onDownload={() => jobPath && action.run(() => openBlob(`${jobPath}/csv`, "menu-import.csv"))}
        />
      ) : null}
    </Card>
  );
}

function Review(props: {
  review: MenuImportReview;
  rows: MenuImportRow[];
  defaults: MenuImportDefaults;
  dirty: boolean;
  busy: boolean;
  onEdit: (index: number, patch: Partial<MenuImportRow>) => void;
  onDefaults: (d: MenuImportDefaults) => void;
  onSave: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  onDownload: () => void;
}) {
  const { review, rows, defaults, dirty, busy } = props;
  const diff = review.diff;
  const included = rows.filter((r) => !r.skip);
  const failing = review.rows.filter((r) => !r.skip && r.errors.length > 0).length;
  const changes = diff ? diff.added.length + diff.changed.length : 0;
  const taxOptions = (liquor: boolean) => review.tax_classes.filter((t) => t.liquor === liquor);
  const usage = review.job.usage;

  if (rows.length === 0) {
    return <EmptyState title="Nothing was found" action={<button type="button" onClick={props.onCancel}>Start over</button>}>We could not find any menu items in your files.</EmptyState>;
  }

  return (
    <>
      <h3>Check your menu</h3>
      <p className="muted">
        {included.length} items to import{usage ? `, read from ${usage.pages} page${usage.pages === 1 ? "" : "s"}` : ""}. Fix anything that is wrong, then add it to your menu. Nothing changes until you do.
      </p>
      {review.general_errors.map((m) => <p key={m} className="error" role="alert">{m}</p>)}

      <div className="inline">
        <Field label="Tax class for food" hint="Used for every food row.">
          <select value={defaults.food_tax_class ?? ""} onChange={(e) => props.onDefaults({ ...defaults, food_tax_class: e.target.value || null })}>
            <option value="">Choose…</option>
            {taxOptions(false).map((t) => <option key={t.name}>{t.name}</option>)}
          </select>
        </Field>
        {rows.some((r) => r.is_liquor && !r.skip) ? (
          <Field label="Tax class for liquor" hint="Used for every liquor row.">
            <select value={defaults.liquor_tax_class ?? ""} onChange={(e) => props.onDefaults({ ...defaults, liquor_tax_class: e.target.value || null })}>
              <option value="">Choose…</option>
              {taxOptions(true).map((t) => <option key={t.name}>{t.name}</option>)}
            </select>
          </Field>
        ) : null}
      </div>

      {review.matches_existing > 0 ? (
        <p className="banner" role="status">
          {review.matches_existing} item{review.matches_existing === 1 ? " is" : "s are"} already on your menu and will be updated with the details below. Tick Skip to leave one as it is.
        </p>
      ) : null}
      {review.similar_existing > 0 ? (
        <p className="banner" role="status">
          {review.similar_existing} item{review.similar_existing === 1 ? " looks" : "s look"} like something already on your menu. Skip it if it is the same dish.
        </p>
      ) : null}

      <table className="stacked review">
        <thead>
          <tr><th>Skip</th><th>Category</th><th>Item</th><th>Price (₹)</th><th>Type</th><th>Liquor</th></tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const checked = review.rows[i];
            const label = row.item || `row ${i + 1}`;
            return (
              <tr key={i} className={row.skip ? "skipped" : undefined}>
                <td data-label="Skip">
                  <input type="checkbox" checked={row.skip} aria-label={`Skip ${label}`} onChange={(e) => props.onEdit(i, { skip: e.target.checked })} />
                </td>
                <td data-label="Category"><input value={row.category} aria-label={`Category for ${label}`} onChange={(e) => props.onEdit(i, { category: e.target.value })} /></td>
                <td data-label="Item">
                  <input value={row.item} aria-label={`Name for ${label}`} onChange={(e) => props.onEdit(i, { item: e.target.value })} />
                  <span className="review-notes">
                    {checked?.errors.map((m) => <Badge key={m} tone="danger">{m}</Badge>)}
                    {(row.notes ?? []).map((m) => <Badge key={m} tone="warn">{m}</Badge>)}
                    {checked?.similar_to ? <Badge tone="info">Looks like “{checked.similar_to}”</Badge> : null}
                  </span>
                </td>
                <td data-label="Price (₹)"><input inputMode="decimal" value={row.price} aria-label={`Price for ${label}`} onChange={(e) => props.onEdit(i, { price: e.target.value })} /></td>
                <td data-label="Type">
                  <select aria-label={`Veg or non-veg for ${label}`} value={row.veg === null || row.veg === undefined ? "" : row.veg ? "veg" : "non"}
                    onChange={(e) => props.onEdit(i, { veg: e.target.value === "" ? null : e.target.value === "veg" })}>
                    <option value="">Not marked</option><option value="veg">Veg</option><option value="non">Non-veg</option>
                  </select>
                </td>
                <td data-label="Liquor"><input type="checkbox" checked={row.is_liquor} aria-label={`${label} is liquor`} onChange={(e) => props.onEdit(i, { is_liquor: e.target.checked })} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {diff && !dirty ? (
        <>
          <h3>What will change</h3>
          <ul>
            <li>{diff.added.length} new items{diff.new_categories.length ? `, ${diff.new_categories.length} new categories (${diff.new_categories.join(", ")})` : ""}</li>
            <li>{diff.changed.length} existing items updated{diff.unchanged ? `, ${diff.unchanged} already match` : ""}</li>
          </ul>
          {diff.changed.length ? (
            <table className="stacked">
              <thead><tr><th>Existing item</th><th>What changes</th></tr></thead>
              <tbody>{diff.changed.map((c) => (
                <tr key={`${c.category}/${c.item}`}><td data-label="Existing item">{c.item}</td><td data-label="What changes">{Object.entries(c.changes).map(([field, [from, to]]) => (
                  <div key={field}>{field === "price_paise" ? `price ${formatInr(from as number)} → ${formatInr(to as number)}` : `${field}: ${JSON.stringify(from)} → ${JSON.stringify(to)}`}</div>
                ))}</td></tr>
              ))}</tbody>
            </table>
          ) : null}
        </>
      ) : null}
      {failing > 0 && !dirty ? <p className="error" role="alert">{failing} row{failing === 1 ? " needs" : "s need"} fixing before you can add this menu.</p> : null}
      {dirty ? <p className="muted" role="status">You have changes. Update the preview to check them.</p> : null}

      <div className="inline">
        {dirty ? (
          <button type="button" disabled={busy} onClick={props.onSave}>Update preview</button>
        ) : (
          <button type="button" disabled={busy || !diff || changes === 0} onClick={props.onConfirm}>Add to menu</button>
        )}
        <button type="button" className="secondary" disabled={busy || dirty} onClick={props.onDownload}>Download CSV</button>
        <button type="button" className="tertiary" disabled={busy} onClick={props.onCancel}>Discard</button>
      </div>
    </>
  );
}

