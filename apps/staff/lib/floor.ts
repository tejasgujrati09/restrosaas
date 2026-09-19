export const STATE_LABELS: Record<string, string> = {
  empty: "Free",
  seated: "Seated",
  order_pending: "Order in progress",
  bill_requested: "Bill requested",
};

const LINE_STATUS: Record<string, string> = {
  placed: "Sent",
  accepted: "Accepted",
  preparing: "Being prepared",
  ready: "Ready to serve",
  served: "Served",
  cancelled: "Cancelled",
  voided: "Removed",
};

/** How loud a line or round status should be: waiting on the kitchen is amber, ready and
 *  served are green, the rest is neutral. Words always accompany the colour. */
export function statusTone(status: string): "neutral" | "info" | "warn" | "ok" {
  switch (status) {
    case "placed":
      return "info";
    case "preparing":
      return "warn";
    case "ready":
    case "served":
      return "ok";
    default:
      return "neutral";
  }
}

export function lineStatus(status: string): string {
  return LINE_STATUS[status] ?? status;
}

export function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** Whole minutes since `iso`, for ticket and request ages. */
export function minutesSince(iso: string, now: number): number {
  return Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60_000));
}

export function secondsUntil(iso: string, now: number): number {
  return Math.max(0, Math.ceil((new Date(iso).getTime() - now) / 1000));
}

/** Amber from 8 minutes, red from 15 (docs/UI-FLOWS.md §3). */
export function ageClass(minutes: number): string {
  if (minutes >= 15) return "age-red";
  if (minutes >= 8) return "age-amber";
  return "age-ok";
}

/** Where a signed-in person should land: their working screen. */
export function homeFor(roles: string[]): string {
  if (roles.includes("owner")) return "menu";
  if (roles.includes("manager") || roles.includes("waiter")) return "floor";
  if (roles.includes("kitchen") || roles.includes("bar")) return "kitchen";
  return "menu";
}
