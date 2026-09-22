import { formatInr } from "@restosaas/ui";
import type { Kpi } from "./types";

// Display helpers only. Every figure, rule and definition comes from the API.

export type Preset =
  | "today"
  | "yesterday"
  | "last_7_days"
  | "last_30_days"
  | "this_week"
  | "this_month"
  | "previous_month"
  | "custom";

export const PRESETS: { value: Preset; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "last_7_days", label: "Last 7 days" },
  { value: "last_30_days", label: "Last 30 days" },
  { value: "this_week", label: "This week" },
  { value: "this_month", label: "This month" },
  { value: "previous_month", label: "Previous month" },
  { value: "custom", label: "Custom range" },
];

export type RangeChoice = { preset: Preset; from: string; to: string };

/** Query string for a range; null while a custom range is incomplete. */
export function rangeParams(range: RangeChoice): URLSearchParams | null {
  const params = new URLSearchParams({ range: range.preset });
  if (range.preset === "custom") {
    if (!range.from || !range.to) return null;
    params.set("from", range.from);
    params.set("to", range.to);
  }
  return params;
}

/** "14m 32s", "45s", "1h 05m". Under a minute shows seconds; never rounds to a false zero. */
export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function hourLabel(hour: number): string {
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h} ${hour % 24 < 12 ? "AM" : "PM"}`;
}

export function windowsLabel(windows: { start_hour: number; end_hour: number }[]): string {
  return windows.map((w) => `${hourLabel(w.start_hour)} to ${hourLabel(w.end_hour % 24)}`).join(", ");
}

export function formatKpiValue(kpi: Pick<Kpi, "unit">, value: number | null): string {
  if (value === null) return "No data";
  switch (kpi.unit) {
    case "paise":
      return formatInr(Math.round(value));
    case "seconds":
      return formatDuration(value);
    case "percent":
      return `${value}%`;
    case "ratio":
      return value.toFixed(1);
    default:
      return String(Math.round(value));
  }
}

/** Only when the API gave a valid comparison. Direction is stated, never judged good or bad:
 *  a longer prep time and a bigger order value both go "up". */
export function changeText(kpi: Pick<Kpi, "change_pct">): string | null {
  if (kpi.change_pct === null || kpi.change_pct === undefined) return null;
  if (kpi.change_pct === 0) return "No change vs previous period";
  const arrow = kpi.change_pct > 0 ? "↑" : "↓";
  return `${arrow} ${Math.abs(kpi.change_pct)}% vs previous period`;
}

export function basisText(kpi: Pick<Kpi, "n" | "basis">): string {
  return `Based on ${kpi.n.toLocaleString("en-IN")} ${kpi.basis}`;
}

export function shortDate(iso: string): string {
  const [y = 1970, m = 1, d = 1] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

export function rangeText(start: string, end: string): string {
  return start === end ? shortDate(start) : `${shortDate(start)} to ${shortDate(end)}`;
}

export function localTime(iso: string, timeZone: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  });
}

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export const STATUS_LABELS: Record<string, string> = {
  placed: "Placed",
  accepted: "Accepted",
  preparing: "Preparing",
  ready: "Ready",
  served: "Served",
  cancelled: "Cancelled",
};

export const QUADRANT_LABELS: Record<string, string> = {
  high_volume_high_value: "High volume, high value",
  high_volume_low_value: "High volume, lower value",
  low_volume_high_value: "Lower volume, high value",
  low_volume_low_value: "Lower volume, lower value",
};

/** Bar heights as a share of the largest value; a real value never renders as an empty bar. */
export function barShares(values: (number | null)[]): number[] {
  const top = Math.max(0, ...values.map((v) => v ?? 0));
  return values.map((v) => (!v || top === 0 ? 0 : Math.max((v / top) * 100, 2)));
}

/** Heat for a heatmap cell, 0 to 100. */
export function heatShare(value: number, top: number): number {
  return value <= 0 || top <= 0 ? 0 : Math.max(Math.round((value / top) * 100), 8);
}
