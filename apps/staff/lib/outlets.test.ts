import { describe, expect, it } from "vitest";
import { groupClaims, initialOf, rolesPhrase } from "./outlets";

const claim = (outlet_id: string, role: string, restaurant_id = "r1") => ({ restaurant_id, outlet_id, role });

describe("groupClaims", () => {
  it("makes one card per outlet, with the highest role first", () => {
    const out = groupClaims([claim("o1", "waiter"), claim("o2", "owner"), claim("o1", "manager")]);
    expect(out).toEqual([
      { outletId: "o1", restaurantId: "r1", roles: ["manager", "waiter"] },
      { outletId: "o2", restaurantId: "r1", roles: ["owner"] },
    ]);
  });

  it("ignores a repeated role and puts unknown roles last", () => {
    const out = groupClaims([claim("o1", "mystery"), claim("o1", "bar"), claim("o1", "bar")]);
    expect(out[0]?.roles).toEqual(["bar", "mystery"]);
  });

  it("returns nothing for no claims", () => {
    expect(groupClaims([])).toEqual([]);
  });
});

describe("initialOf", () => {
  it("uses the first letter, upper case", () => {
    expect(initialOf("  demo bar")).toBe("D");
    expect(initialOf("पुजाबी")).toBe("प");
  });
  it("falls back to a question mark", () => {
    expect(initialOf("   ")).toBe("?");
  });
});

describe("rolesPhrase", () => {
  it("reads as a short phrase", () => {
    expect(rolesPhrase(["owner"])).toBe("Owner");
    expect(rolesPhrase(["manager", "waiter"])).toBe("Manager and waiter");
    expect(rolesPhrase(["owner", "manager", "waiter"])).toBe("Owner, manager and waiter");
    expect(rolesPhrase([])).toBe("");
  });
});
