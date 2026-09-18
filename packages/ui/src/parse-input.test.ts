import { describe, expect, it } from "vitest";
import { formatBp, paiseToInput, parsePercentToBp, parseRupees } from "./parse-input";

describe("parseRupees", () => {
  it.each([
    ["120", 12000],
    ["120.5", 12050],
    ["120.05", 12005],
    ["₹1,250.75", 125075],
    [" 0 ", 0],
    ["0.10", 10],
  ])("%s -> %i paise", (text, paise) => {
    expect(parseRupees(text)).toBe(paise);
  });

  it.each(["", "abc", "1.234", "-5", "1e3", "1.2.3", ".5"])("rejects %j", (text) => {
    expect(parseRupees(text)).toBeNull();
  });

  it("is exact where floats are not (19.99 * 100 is 1998.9999999999998)", () => {
    expect(parseRupees("19.99")).toBe(1999);
    expect(parseRupees("1.15")).toBe(115);
  });
});

describe("percent basis points", () => {
  it.each([
    ["5", 500],
    ["12.5", 1250],
    ["18%", 1800],
    ["0.25", 25],
  ])("%s -> %i bp", (text, bp) => {
    expect(parsePercentToBp(text)).toBe(bp);
  });
  it("rejects junk", () => {
    expect(parsePercentToBp("five")).toBeNull();
  });
  it("formats back", () => {
    expect(formatBp(1250)).toBe("12.5");
    expect(formatBp(500)).toBe("5");
    expect(formatBp(25)).toBe("0.25");
  });
});

describe("paiseToInput", () => {
  it("round-trips", () => {
    expect(paiseToInput(12050)).toBe("120.50");
    expect(paiseToInput(5)).toBe("0.05");
    expect(parseRupees(paiseToInput(12345))).toBe(12345);
  });
});
