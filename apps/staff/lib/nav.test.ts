import { describe, expect, it } from "vitest";
import { NAV, sectionOf, splitForTabBar, usesDarkTheme, visibleNav } from "./nav";

const hrefs = (roles: string[]) => visibleNav(roles).flatMap((g) => g.items.map((i) => i.href));

describe("visibleNav", () => {
  it("shows an owner everything, in four groups", () => {
    expect(visibleNav(["owner"]).map((g) => g.label)).toEqual(["Service", "Insights", "Manage", "Settings"]);
    expect(hrefs(["owner"])).toEqual(
      NAV.flatMap((g) => g.items.map((i) => i.href)),
    );
  });

  it("keeps a waiter to the floor, requests and the menu", () => {
    expect(hrefs(["waiter"])).toEqual(["floor", "requests", "menu"]);
  });

  it("keeps kitchen and bar to the queue and the menu", () => {
    expect(hrefs(["kitchen"])).toEqual(["kitchen", "menu"]);
    expect(hrefs(["bar"])).toEqual(["kitchen", "menu"]);
  });

  it("gives a manager everything except setup, and drops the empty group", () => {
    expect(hrefs(["manager"])).not.toContain("setup");
    expect(visibleNav(["manager"]).map((g) => g.label)).toEqual(["Service", "Insights", "Manage"]);
  });

  it("merges several roles and shows nothing without one", () => {
    expect(hrefs(["waiter", "kitchen"])).toEqual(["floor", "requests", "kitchen", "menu"]);
    expect(visibleNav([])).toEqual([]);
  });
});

describe("usesDarkTheme", () => {
  it("is dark for people who work the floor and the pass", () => {
    expect(usesDarkTheme(["waiter"])).toBe(true);
    expect(usesDarkTheme(["kitchen", "bar"])).toBe(true);
  });

  it("is light for anyone who also manages, and before roles are known", () => {
    expect(usesDarkTheme(["waiter", "manager"])).toBe(false);
    expect(usesDarkTheme(["owner"])).toBe(false);
    expect(usesDarkTheme([])).toBe(false);
  });
});

describe("sectionOf", () => {
  it("reads the section from an outlet path", () => {
    expect(sectionOf("/o/abc/floor")).toBe("floor");
    expect(sectionOf("/o/abc/floor/tab-1/add")).toBe("floor");
    expect(sectionOf("/o/abc/price-rules")).toBe("price-rules");
    expect(sectionOf("/login")).toBe("");
  });
});

describe("splitForTabBar", () => {
  const items = NAV.flatMap((g) => g.items);

  it("puts the first three on the bar and the rest under More", () => {
    const { primary, more } = splitForTabBar(items);
    expect(primary.map((i) => i.href)).toEqual(["floor", "requests", "kitchen"]);
    expect(more).toHaveLength(items.length - 3);
  });

  it("leaves More empty when everything fits", () => {
    expect(splitForTabBar(items.slice(0, 2)).more).toEqual([]);
  });
});
