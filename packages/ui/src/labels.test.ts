import { describe, expect, it } from "vitest";
import { humanize, roleLabel, sentenceCase } from "./labels";

describe("sentenceCase", () => {
  it("capitalises the first letter and leaves the rest as written", () => {
    expect(sentenceCase("floor")).toBe("Floor");
    expect(sentenceCase("main hall")).toBe("Main hall");
    expect(sentenceCase("VIP lounge")).toBe("VIP lounge");
    expect(sentenceCase("Terrace")).toBe("Terrace");
  });

  it("copes with padding, empty and long text", () => {
    expect(sentenceCase("  bar  ")).toBe("Bar");
    expect(sentenceCase("")).toBe("");
    const long = "a".repeat(200);
    expect(sentenceCase(long)).toBe(`A${"a".repeat(199)}`);
  });
});

describe("humanize", () => {
  it("turns stored codes into a sentence", () => {
    expect(humanize("order_pending")).toBe("Order pending");
    expect(humanize("bill-requested")).toBe("Bill requested");
    expect(humanize("trial")).toBe("Trial");
  });
});

describe("roleLabel", () => {
  it("names every role and falls back for one it does not know", () => {
    for (const [role, label] of [["waiter", "Waiter"], ["kitchen", "Kitchen"], ["bar", "Bar"], ["manager", "Manager"], ["owner", "Owner"]]) {
      expect(roleLabel(role as string)).toBe(label);
    }
    expect(roleLabel("head_chef")).toBe("Head chef");
  });
});

import { stateName } from "./gst-states";

describe("stateName", () => {
  it("names a GST state code and leaves an unknown one alone", () => {
    expect(stateName("29")).toBe("Karnataka");
    expect(stateName("99")).toBe("99");
  });
});
