import { describe, expect, it } from "vitest";
import { toE164 } from "./phone";

describe("toE164", () => {
  it.each([
    ["9876543210", "+919876543210"],
    ["98765 43210", "+919876543210"],
    ["098765-43210", "+919876543210"],
    ["+919876543210", "+919876543210"],
    ["+14155550123", "+14155550123"],
  ])("%s -> %s", (input, out) => expect(toE164(input)).toBe(out));

  it.each(["", "12345", "5876543210", "+0123456789", "abc"])("rejects %j", (input) => {
    expect(toE164(input)).toBeNull();
  });
});
