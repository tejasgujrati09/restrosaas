import { describe, expect, it } from "vitest";
import { ageClass, homeFor, lineStatus, minutesSince, secondsUntil } from "./floor";

describe("ageClass", () => {
  it("turns amber at 8 minutes and red at 15", () => {
    expect(ageClass(0)).toBe("age-ok");
    expect(ageClass(7)).toBe("age-ok");
    expect(ageClass(8)).toBe("age-amber");
    expect(ageClass(14)).toBe("age-amber");
    expect(ageClass(15)).toBe("age-red");
  });
});

describe("homeFor", () => {
  it("sends each role to the screen it works from", () => {
    expect(homeFor(["waiter"])).toBe("floor");
    expect(homeFor(["manager"])).toBe("floor");
    expect(homeFor(["kitchen"])).toBe("kitchen");
    expect(homeFor(["bar"])).toBe("kitchen");
    expect(homeFor(["owner"])).toBe("menu");
    expect(homeFor(["waiter", "owner"])).toBe("menu");
    expect(homeFor([])).toBe("menu");
  });
});

describe("time helpers", () => {
  const now = Date.parse("2026-09-18T12:10:00Z");
  it("counts whole minutes and never goes negative", () => {
    expect(minutesSince("2026-09-18T12:00:30Z", now)).toBe(9);
    expect(minutesSince("2026-09-18T12:20:00Z", now)).toBe(0);
  });
  it("rounds a countdown up", () => {
    expect(secondsUntil("2026-09-18T12:10:00.400Z", now)).toBe(1);
    expect(secondsUntil("2026-09-18T12:00:00Z", now)).toBe(0);
  });
  it("names line statuses in plain words, falling back to the raw value", () => {
    expect(lineStatus("ready")).toBe("Ready to serve");
    expect(lineStatus("dispatched")).toBe("dispatched");
  });
});
