import { beforeEach, describe, expect, it } from "vitest";
import { currentToasts, dismissToast, toast } from "./toast";

describe("toast store", () => {
  beforeEach(() => toast.clear());

  it("does not stack the same message twice", () => {
    const a = toast.ok("Saved");
    expect(toast.ok("Saved")).toBe(a);
    expect(currentToasts()).toHaveLength(1);
  });

  it("keeps a message of another tone apart", () => {
    toast.ok("Saved");
    toast.error("Saved");
    expect(currentToasts().map((t) => t.tone)).toEqual(["ok", "error"]);
  });

  it("dismisses one toast and ignores an unknown id", () => {
    const a = toast.ok("One");
    toast.ok("Two");
    dismissToast(a);
    dismissToast(9999);
    expect(currentToasts().map((t) => t.message)).toEqual(["Two"]);
  });

  it("shows at most three, the newest", () => {
    for (const m of ["1", "2", "3", "4"]) toast.error(m);
    expect(currentToasts().map((t) => t.message)).toEqual(["2", "3", "4"]);
  });

  it("clears everything", () => {
    toast.ok("x");
    toast.clear();
    expect(currentToasts()).toEqual([]);
  });
});
