import type { AuditEntry, PlatformRestaurant } from "./types";

export type StatusFilter = "all" | "active" | "suspended";

/** Search by restaurant or registered name, and by status. Case-insensitive. */
export function filterRestaurants(list: PlatformRestaurant[], query: string, status: StatusFilter): PlatformRestaurant[] {
  const q = query.trim().toLowerCase();
  return list.filter(
    (r) =>
      (status === "all" || r.status === status) &&
      (q === "" || r.brand_name.toLowerCase().includes(q) || r.legal_name.toLowerCase().includes(q)),
  );
}

export function countByStatus(list: PlatformRestaurant[]): Record<StatusFilter, number> {
  return {
    all: list.length,
    active: list.filter((r) => r.status === "active").length,
    suspended: list.filter((r) => r.status === "suspended").length,
  };
}

const ACTIONS: Record<string, string> = {
  "restaurant.suspended": "Suspended",
  "restaurant.reactivated": "Reactivated",
  "restaurant.voice_allowed": "Allowed voice orders",
  "restaurant.voice_disallowed": "Turned voice orders off",
};

/** "restaurant.suspended" -> "Suspended"; anything unknown is made readable rather than hidden. */
export function actionLabel(action: string): string {
  const known = ACTIONS[action];
  if (known) return known;
  const words = action.replace(/[._]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Unknown action";
}

/** Who did it: their name, else their phone, else "System". */
export function actorLabel(e: Pick<AuditEntry, "actor_name" | "actor_phone">): string {
  return e.actor_name?.trim() || e.actor_phone || "System";
}

/** The reason recorded with an entry, if any. */
export function reasonOf(e: Pick<AuditEntry, "after">): string | null {
  const reason = e.after && typeof e.after === "object" ? (e.after as Record<string, unknown>).reason : null;
  return typeof reason === "string" && reason.trim() ? reason : null;
}

export function initialOf(name: string): string {
  const first = [...name.trim()][0];
  return first ? first.toUpperCase() : "?";
}

export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}

/** How far away a plan's last day is, in words: "in 12 days", "today", "3 days ago". */
export function expiryLabel(days: number | null): string {
  if (days === null) return "No expiry set";
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  return days > 0 ? `in ${days} days` : `${-days} days ago`;
}

/** Ended is danger, within two weeks is a warning, otherwise fine; no date is neutral. */
export function expiryTone(days: number | null): "neutral" | "ok" | "warn" | "danger" {
  if (days === null) return "neutral";
  if (days < 0) return "danger";
  return days <= 14 ? "warn" : "ok";
}

/** Whole days between two moments, rounded down: how long ago something happened. */
export function daysSince(iso: string, now: Date = new Date()): number {
  return Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / 86_400_000));
}

export function agoLabel(iso: string, now: Date = new Date()): string {
  const d = daysSince(iso, now);
  if (d === 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 60) return `${d} days ago`;
  return `${Math.floor(d / 30)} months ago`;
}

const PHONE = /^\+91(\d{5})(\d{5})$/;
/** +919876543210 -> +91 98765 43210; anything else is shown as it is. */
export function formatPhone(phone: string): string {
  const m = PHONE.exec(phone);
  return m ? `+91 ${m[1]} ${m[2]}` : phone;
}
