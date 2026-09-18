const STATUS_LABELS: Record<string, string> = {
  placed: "Sent",
  accepted: "Accepted",
  preparing: "Being prepared",
  ready: "Ready",
  served: "Served",
  cancelled: "Cancelled",
  voided: "Removed",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** Whole seconds from now until `iso`, never negative. */
export function secondsUntil(iso: string, now: number): number {
  return Math.max(0, Math.ceil((new Date(iso).getTime() - now) / 1000));
}
