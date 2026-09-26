"use client";

import { useEffect, useSyncExternalStore } from "react";

export type ToastTone = "ok" | "error";
export type ToastItem = { id: number; tone: ToastTone; message: string };

/** How long a confirmation stays. Errors stay until dismissed. */
export const TOAST_MS = 4000;
const MAX_VISIBLE = 3;

let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function push(tone: ToastTone, message: string): number {
  // The same message twice in a row is one toast, not a stack of them.
  const same = items.find((t) => t.tone === tone && t.message === message);
  if (same) return same.id;
  const id = nextId++;
  items = [...items, { id, tone, message }].slice(-MAX_VISIBLE);
  emit();
  return id;
}

export function dismissToast(id: number) {
  items = items.filter((t) => t.id !== id);
  emit();
}

/** Feedback for something the person just did. It floats above the page, so showing or hiding
 *  it never moves anything (docs/DESIGN.md "Feedback and layout stability"). */
export const toast = {
  ok: (message: string) => push("ok", message),
  error: (message: string) => push("error", message),
  clear: () => {
    items = [];
    emit();
  },
};

/** The toasts showing now (for tests). */
export const currentToasts = (): ToastItem[] => items;

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const snapshot = () => items;
const empty: ToastItem[] = [];

function Item({ item }: { item: ToastItem }) {
  useEffect(() => {
    if (item.tone !== "ok") return;
    const timer = window.setTimeout(() => dismissToast(item.id), TOAST_MS);
    return () => window.clearTimeout(timer);
  }, [item.id, item.tone]);
  const error = item.tone === "error";
  return (
    <div className={error ? "toast error" : "toast ok"} role={error ? "alert" : "status"}>
      <span className="toast-mark" aria-hidden="true">
        {error ? "!" : "✓"}
      </span>
      <span className="toast-text">{item.message}</span>
      {error ? (
        <button type="button" className="tertiary" onClick={() => dismissToast(item.id)}>
          Dismiss
        </button>
      ) : null}
    </div>
  );
}

/** Mount once per app, in the root layout. */
export function ToastHost() {
  const list = useSyncExternalStore(subscribe, snapshot, () => empty);
  return (
    <div className="toasts" role="region" aria-label="Notifications">
      {list.map((t) => (
        <Item key={t.id} item={t} />
      ))}
    </div>
  );
}
