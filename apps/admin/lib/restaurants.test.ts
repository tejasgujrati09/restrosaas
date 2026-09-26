import { describe, expect, it } from "vitest";
import { actionLabel, actorLabel, agoLabel, countByStatus, daysSince, expiryLabel, expiryTone, filterRestaurants, formatPhone, initialOf, reasonOf } from "./restaurants";
import type { PlatformRestaurant } from "./types";

const r = (brand: string, legal: string, status: "active" | "suspended"): PlatformRestaurant => ({
  id: brand,
  brand_name: brand,
  legal_name: legal,
  gstin: null,
  plan: "trial",
  status,
  voice_orders_allowed: false,
  plan_expires_at: null,
  created_at: "2026-09-01T00:00:00Z",
});
const list = [r("Copper Still", "Copper Hospitality Pvt Ltd", "active"), r("Demo Bar", "Demo LLP", "suspended"), r("Chai Point", "CP Foods", "active")];

describe("filterRestaurants", () => {
  it("returns everything for no query and all statuses", () => {
    expect(filterRestaurants(list, "", "all")).toHaveLength(3);
  });
  it("matches brand or registered name, ignoring case and spaces at the ends", () => {
    expect(filterRestaurants(list, "  copper ", "all").map((x) => x.brand_name)).toEqual(["Copper Still"]);
    expect(filterRestaurants(list, "llp", "all").map((x) => x.brand_name)).toEqual(["Demo Bar"]);
  });
  it("filters by status, alone or with a query", () => {
    expect(filterRestaurants(list, "", "suspended").map((x) => x.brand_name)).toEqual(["Demo Bar"]);
    expect(filterRestaurants(list, "demo", "active")).toEqual([]);
  });
});

describe("countByStatus", () => {
  it("counts each status and the total", () => {
    expect(countByStatus(list)).toEqual({ all: 3, active: 2, suspended: 1 });
    expect(countByStatus([])).toEqual({ all: 0, active: 0, suspended: 0 });
  });
});

describe("audit labels", () => {
  it("names the known actions and makes unknown ones readable", () => {
    expect(actionLabel("restaurant.suspended")).toBe("Suspended");
    expect(actionLabel("restaurant.reactivated")).toBe("Reactivated");
    expect(actionLabel("menu_item.price_changed")).toBe("Menu item price changed");
    expect(actionLabel("")).toBe("Unknown action");
  });
  it("names the actor by name, then phone, then System", () => {
    expect(actorLabel({ actor_name: " Asha ", actor_phone: "+91" })).toBe("Asha");
    expect(actorLabel({ actor_name: null, actor_phone: "+919" })).toBe("+919");
    expect(actorLabel({ actor_name: null, actor_phone: null })).toBe("System");
  });
  it("reads the reason from the after snapshot, when there is one", () => {
    expect(reasonOf({ after: { status: "suspended", reason: "Unpaid invoice" } })).toBe("Unpaid invoice");
    expect(reasonOf({ after: { status: "active", reason: null } })).toBeNull();
    expect(reasonOf({ after: null })).toBeNull();
  });
});

describe("initialOf", () => {
  it("uses the first letter, or a question mark", () => {
    expect(initialOf(" copper")).toBe("C");
    expect(initialOf("")).toBe("?");
  });
});

describe("plan expiry wording", () => {
  it("says how far away the last day is", () => {
    expect([null, 0, 1, -1, 12, -3].map(expiryLabel)).toEqual(["No expiry set", "today", "tomorrow", "yesterday", "in 12 days", "3 days ago"]);
  });

  it("is danger once ended, a warning inside two weeks, and neutral with no date", () => {
    expect([null, -1, 0, 14, 15].map(expiryTone)).toEqual(["neutral", "danger", "warn", "warn", "ok"]);
  });
});

describe("how long ago", () => {
  const now = new Date("2026-09-26T12:00:00Z");
  it("counts whole days and never goes negative", () => {
    expect(daysSince("2026-09-26T01:00:00Z", now)).toBe(0);
    expect(daysSince("2026-09-20T12:00:00Z", now)).toBe(6);
    expect(daysSince("2026-10-01T00:00:00Z", now)).toBe(0);
  });

  it("uses days, then months", () => {
    expect(["2026-09-26T05:00:00Z", "2026-09-25T05:00:00Z", "2026-09-06T00:00:00Z", "2026-05-01T00:00:00Z"].map((i) => agoLabel(i, now))).toEqual(["today", "yesterday", "20 days ago", "4 months ago"]);
  });
});

describe("formatPhone", () => {
  it("groups an Indian mobile and leaves anything else alone", () => {
    expect(formatPhone("+919876543210")).toBe("+91 98765 43210");
    expect(formatPhone("+4412345")).toBe("+4412345");
  });
});
