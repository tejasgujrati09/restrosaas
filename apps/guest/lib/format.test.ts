import { describe, expect, it } from "vitest";
import { secondsUntil, statusLabel } from "./format";

describe("statusLabel", () => {
  it("uses plain words for every state a guest can see", () => {
    expect(statusLabel("placed")).toBe("Sent");
    expect(statusLabel("preparing")).toBe("Being prepared");
    expect(statusLabel("voided")).toBe("Removed");
  });
  it("falls back to the raw status rather than hiding it", () => {
    expect(statusLabel("dispatched")).toBe("dispatched");
  });
});

describe("secondsUntil", () => {
  const now = Date.parse("2026-09-18T12:00:00Z");
  it("rounds up so 0.4 s left still shows 1", () => {
    expect(secondsUntil("2026-09-18T12:00:00.400Z", now)).toBe(1);
    expect(secondsUntil("2026-09-18T12:01:00Z", now)).toBe(60);
  });
  it("never goes negative", () => {
    expect(secondsUntil("2026-09-18T11:59:00Z", now)).toBe(0);
  });
});
