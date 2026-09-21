import { describe, expect, it } from "vitest";
import { ORDER_TABS, daysBefore, emptyText, ordersPath, sourceLabel, statusView, summariseItems, taxLabel, ticketText, voicePollMs } from "./orders";

const base = { group: "new", source: "", q: "", from: "", to: "", offset: 0 } as const;

describe("ordersPath", () => {
  it("sends only the group when nothing else is chosen", () => {
    expect(ordersPath("o1", base)).toBe("/v1/outlets/o1/staff/orders?group=new");
  });

  it("adds every filter that is set and trims the search", () => {
    const url = ordersPath("o1", { ...base, group: "ready", source: "voice", q: "  rahul ", from: "2026-09-01", to: "2026-09-02", offset: 50 });
    const p = new URL(url, "http://x").searchParams;
    expect(Object.fromEntries(p)).toEqual({
      group: "ready",
      source: "voice",
      q: "rahul",
      date_from: "2026-09-01",
      date_to: "2026-09-02",
      offset: "50",
    });
  });

  it("ignores a blank search", () => {
    expect(ordersPath("o1", { ...base, q: "   " })).not.toContain("q=");
  });
});

describe("labels", () => {
  it("has a tab for every group the API returns, in the order an owner works", () => {
    expect(ORDER_TABS.map((t) => t.key)).toEqual(["new", "in_progress", "ready", "completed", "cancelled"]);
    for (const t of ORDER_TABS) expect(emptyText(t.key)).not.toBe("");
  });

  it("names every source and status, and falls back to the raw value", () => {
    expect(sourceLabel("voice")).toBe("Voice");
    expect(sourceLabel("customer")).toBe("QR order");
    expect(sourceLabel("mystery")).toBe("mystery");
    expect(statusView("placed")).toEqual({ label: "New", tone: "warn" });
    expect(statusView("cancelled").tone).toBe("danger");
    expect(statusView("odd")).toEqual({ label: "odd", tone: "neutral" });
  });
});

describe("daysBefore", () => {
  it("steps back across month and year ends", () => {
    expect(daysBefore("2026-09-21", 7)).toBe("2026-09-14");
    expect(daysBefore("2026-03-02", 3)).toBe("2026-02-27");
    expect(daysBefore("2026-01-01", 1)).toBe("2025-12-31");
  });
});

describe("summariseItems", () => {
  it("shows a few items and counts the rest", () => {
    const items = [1, 2, 3, 4, 5].map((n) => ({ name: `Dish ${n}`, qty: n }));
    expect(summariseItems(items)).toEqual({ shown: ["1 × Dish 1", "2 × Dish 2", "3 × Dish 3"], more: 2 });
    expect(summariseItems(items.slice(0, 2))).toEqual({ shown: ["1 × Dish 1", "2 × Dish 2"], more: 0 });
  });
});

describe("voicePollMs", () => {
  it("asks quickly only while something is in flight", () => {
    expect(voicePollMs("setting_up")).toBe(2_500);
    expect(voicePollMs("turning_off")).toBe(2_500);
    for (const phase of ["active", "off", "failed", "unavailable", undefined]) expect(voicePollMs(phase)).toBe(30_000);
  });
});

describe("pricing and ticket wording", () => {
  it("says when a tax is already inside the item prices", () => {
    expect(taxLabel("CGST", true)).toBe("CGST (included)");
    expect(taxLabel("CGST", false)).toBe("CGST");
  });

  it("names the station, or the kitchen when there is none", () => {
    expect(ticketText(null, "queued")).toBe("Kitchen ticket: queued");
    expect(ticketText("Bar", "ready")).toBe("Bar ticket: ready");
  });
});
