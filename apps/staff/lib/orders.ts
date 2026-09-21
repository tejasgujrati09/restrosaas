/** Labels and small rules for the Orders screen. The API decides the groups, the counts and which
 *  actions are offered; this file only turns them into words and builds the query. */
import type { Tone } from "@restosaas/ui";
import type { OrderGroup } from "./types";

export const ORDER_TABS: { key: OrderGroup; label: string }[] = [
  { key: "new", label: "New" },
  { key: "in_progress", label: "In progress" },
  { key: "ready", label: "Ready" },
  { key: "completed", label: "Completed" },
  { key: "cancelled", label: "Cancelled" },
];

export const SOURCES = ["customer", "waiter", "voice", "aggregator"] as const;
export type Source = (typeof SOURCES)[number];

const SOURCE_LABEL: Record<string, string> = {
  customer: "QR order",
  waiter: "Waiter",
  voice: "Voice",
  aggregator: "Delivery app",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABEL[source] ?? source;
}

const STATUS: Record<string, { label: string; tone: Tone }> = {
  placed: { label: "New", tone: "warn" },
  accepted: { label: "Accepted", tone: "info" },
  preparing: { label: "Preparing", tone: "info" },
  ready: { label: "Ready", tone: "ok" },
  dispatched: { label: "Out for delivery", tone: "info" },
  served: { label: "Served", tone: "ok" },
  delivered: { label: "Delivered", tone: "ok" },
  cancelled: { label: "Cancelled", tone: "danger" },
};

export function statusView(status: string): { label: string; tone: Tone } {
  return STATUS[status] ?? { label: status, tone: "neutral" };
}

const EMPTY: Record<OrderGroup, string> = {
  new: "No new orders. When one arrives it shows up here.",
  in_progress: "Nothing is being prepared right now.",
  ready: "Nothing is waiting to be served.",
  completed: "No completed orders in this period.",
  cancelled: "No cancelled orders in this period.",
};

export function emptyText(group: OrderGroup): string {
  return EMPTY[group];
}

export type OrderFilters = {
  group: OrderGroup;
  source: string;
  q: string;
  from: string;
  to: string;
  offset: number;
};

/** Only what is set goes on the URL, so the server's own defaults (today, in the outlet's time)
 *  apply otherwise. */
export function ordersPath(outletId: string, f: OrderFilters): string {
  const p = new URLSearchParams({ group: f.group });
  if (f.source) p.set("source", f.source);
  if (f.q.trim()) p.set("q", f.q.trim());
  if (f.from) p.set("date_from", f.from);
  if (f.to) p.set("date_to", f.to);
  if (f.offset > 0) p.set("offset", String(f.offset));
  return `/v1/outlets/${outletId}/staff/orders?${p.toString()}`;
}

/** `YYYY-MM-DD` minus whole days, without touching the time zone. */
export function daysBefore(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export const PAGE_SIZE = 50;

/** The most items shown on a card; the rest are counted. */
export function summariseItems(items: { name: string; qty: number }[], max = 3): { shown: string[]; more: number } {
  return { shown: items.slice(0, max).map((i) => `${i.qty} × ${i.name}`), more: Math.max(0, items.length - max) };
}

/** How often to ask again while voice ordering is being set up or turned off. */
export function voicePollMs(phase: string | undefined): number {
  return phase === "setting_up" || phase === "turning_off" ? 2_500 : 30_000;
}

/** "CGST" on its own reads as extra money; when prices already contain the tax, say so. */
export function taxLabel(name: string, included: boolean): string {
  return included ? `${name} (included)` : name;
}

/** One kitchen ticket as a short phrase: "Kitchen ticket: queued", "Bar ticket: ready". */
export function ticketText(station: string | null | undefined, status: string): string {
  return `${station ?? "Kitchen"} ticket: ${status}`;
}
