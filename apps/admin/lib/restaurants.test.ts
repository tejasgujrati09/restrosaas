import { describe, expect, it } from "vitest";
import { actionLabel, actorLabel, countByStatus, filterRestaurants, initialOf, reasonOf } from "./restaurants";
import type { PlatformRestaurant } from "./types";

const r = (brand: string, legal: string, status: "active" | "suspended"): PlatformRestaurant => ({
  id: brand,
  brand_name: brand,
  legal_name: legal,
  gstin: null,
  plan: "trial",
  status,
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
