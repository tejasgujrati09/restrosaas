import { describe, expect, it } from "vitest";
import { ageClass, homeFor, lineStatus, minutesSince, secondsUntil, statusTone } from "./floor";

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

describe("statusTone", () => {
  it("is amber while the kitchen works, green when it is ready or served", () => {
    expect(statusTone("preparing")).toBe("warn");
    expect(statusTone("ready")).toBe("ok");
    expect(statusTone("served")).toBe("ok");
  });

  it("marks a fresh round as info and everything else as neutral", () => {
    expect(statusTone("placed")).toBe("info");
    for (const s of ["accepted", "cancelled", "voided", "anything-else"]) expect(statusTone(s)).toBe("neutral");
  });
});
