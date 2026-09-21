import { describe, expect, it } from "vitest";
import { allowanceCopy, isInFlight, phaseView, stepLabel } from "./voice";

describe("voice admin helpers", () => {
  it("labels every phase and passes unknown ones through", () => {
    for (const p of ["unavailable", "off", "setting_up", "active", "failed", "turning_off"]) {
      expect(phaseView(p).label).not.toBe(p);
    }
    expect(phaseView("active").tone).toBe("ok");
    expect(phaseView("failed").tone).toBe("danger");
    expect(phaseView("new_thing")).toEqual({ label: "new_thing", tone: "neutral" });
  });

  it("is in flight only while a job is running", () => {
    expect(isInFlight("setting_up")).toBe(true);
    expect(isInFlight("turning_off")).toBe(true);
    for (const p of ["active", "failed", "off", "unavailable"]) expect(isInFlight(p)).toBe(false);
  });

  it("states the allowance in plain words that do not rely on the mark alone", () => {
    expect(allowanceCopy(true).headline).toContain("Enabled");
    expect(allowanceCopy(false).headline).toContain("Disabled");
    expect(allowanceCopy(false).body).toBe("Voice ordering is currently unavailable for this restaurant.");
  });

  it("names steps for troubleshooting", () => {
    expect(stepLabel("configure")).toBe("Order integration");
    expect(stepLabel("mystery")).toBe("mystery");
    expect(stepLabel(null)).toBe("");
  });
});
