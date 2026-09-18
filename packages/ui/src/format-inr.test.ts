import { describe, expect, it } from "vitest";
import { formatInr } from "./format-inr";

// Same cases as apps/api/tests/core/test_money.py so the two never drift.
describe("formatInr", () => {
  it.each([
    [0, "₹0.00"],
    [5, "₹0.05"],
    [100, "₹1.00"],
    [150, "₹1.50"],
    [99999, "₹999.99"],
    [100000, "₹1,000.00"],
    [12345600, "₹1,23,456.00"],
    [123456700, "₹12,34,567.00"],
    [-15000, "-₹150.00"],
  ])("formats %i paise as %s", (paise, expected) => {
    expect(formatInr(paise)).toBe(expected);
  });

  it("rejects fractional paise", () => {
    expect(() => formatInr(10.5)).toThrow(RangeError);
  });
});
