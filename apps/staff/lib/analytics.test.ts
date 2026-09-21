import { describe, expect, it } from "vitest";
import {
  barShares,
  basisText,
  changeText,
  formatDuration,
  formatKpiValue,
  heatShare,
  hourLabel,
  localTime,
  rangeParams,
  rangeText,
  windowsLabel,
} from "./analytics";

describe("rangeParams", () => {
  it("sends a preset by itself", () => {
    expect(rangeParams({ preset: "today", from: "", to: "" })?.toString()).toBe("range=today");
  });
  it("needs both dates for a custom range", () => {
    expect(rangeParams({ preset: "custom", from: "2026-09-01", to: "" })).toBeNull();
    expect(rangeParams({ preset: "custom", from: "2026-09-01", to: "2026-09-10" })?.toString()).toBe(
      "range=custom&from=2026-09-01&to=2026-09-10",
    );
  });
});

describe("formatDuration", () => {
  it("reads like a person would say it", () => {
    expect(formatDuration(45)).toBe("45s");
    expect(formatDuration(872)).toBe("14m 32s");
    expect(formatDuration(3900)).toBe("1h 05m");
    expect(formatDuration(0.4)).toBe("0s");
  });
});

describe("hours", () => {
  it("labels 12 hour clock", () => {
    expect([0, 1, 12, 13, 23].map(hourLabel)).toEqual(["12 AM", "1 AM", "12 PM", "1 PM", "11 PM"]);
  });
  it("describes peak windows, wrapping midnight", () => {
    expect(windowsLabel([{ start_hour: 12, end_hour: 14 }, { start_hour: 22, end_hour: 24 }])).toBe(
      "12 PM to 2 PM, 10 PM to 12 AM",
    );
    expect(windowsLabel([])).toBe("");
  });
});

describe("KPI text", () => {
  it("formats by unit and says when there is no data", () => {
    expect(formatKpiValue({ unit: "paise" }, 123456)).toBe("₹1,234.56");
    expect(formatKpiValue({ unit: "seconds" }, 872)).toBe("14m 32s");
    expect(formatKpiValue({ unit: "percent" }, 25)).toBe("25%");
    expect(formatKpiValue({ unit: "ratio" }, 2)).toBe("2.0");
    expect(formatKpiValue({ unit: "count" }, 3)).toBe("3");
    expect(formatKpiValue({ unit: "count" }, null)).toBe("No data");
  });
  it("shows a change only when the API gave one, and states direction without judging it", () => {
    expect(changeText({ change_pct: null })).toBeNull();
    expect(changeText({ change_pct: 8.4 })).toBe("↑ 8.4% vs previous period");
    expect(changeText({ change_pct: -3 })).toBe("↓ 3% vs previous period");
    expect(changeText({ change_pct: 0 })).toBe("No change vs previous period");
  });
  it("states the sample behind a number", () => {
    expect(basisText({ n: 1428, basis: "kitchen tickets" })).toBe("Based on 1,428 kitchen tickets");
  });
});

describe("dates", () => {
  it("prints a range and a local time in the outlet's timezone", () => {
    expect(rangeText("2026-09-18", "2026-09-18")).toBe("18 Sept");
    expect(rangeText("2026-09-12", "2026-09-18")).toBe("12 Sept to 18 Sept");
    expect(localTime("2026-09-18T06:30:00Z", "Asia/Kolkata")).toMatch(/12:00\s?pm/i);
  });
});

describe("bars and heat", () => {
  it("scales to the largest and never hides a real value", () => {
    expect(barShares([10, 5, 0, null])).toEqual([100, 50, 0, 0]);
    expect(barShares([1000, 1])[1]).toBe(2);
    expect(barShares([0, 0])).toEqual([0, 0]);
    expect(barShares([])).toEqual([]);
  });
  it("heat is empty for zero and visible for any activity", () => {
    expect(heatShare(0, 10)).toBe(0);
    expect(heatShare(5, 0)).toBe(0);
    expect(heatShare(10, 10)).toBe(100);
    expect(heatShare(1, 1000)).toBe(8);
  });
});
