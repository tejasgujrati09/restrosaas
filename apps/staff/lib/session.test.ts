import { describe, expect, it } from "vitest";
import { claimsOf, rolesAt } from "./session";

function token(payload: object): string {
  const b64 = btoa(JSON.stringify(payload)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `h.${b64}.s`;
}

describe("claimsOf", () => {
  it("reads the role claims", () => {
    const t = token({ roles: [{ restaurant_id: "r", outlet_id: "o", role: "owner" }] });
    expect(claimsOf(t)).toEqual([{ restaurant_id: "r", outlet_id: "o", role: "owner" }]);
    expect(rolesAt(t, "o")).toEqual(["owner"]);
    expect(rolesAt(t, "other")).toEqual([]);
  });
  it("is empty for missing or malformed tokens", () => {
    expect(claimsOf(null)).toEqual([]);
    expect(claimsOf("garbage")).toEqual([]);
    expect(claimsOf(token({}))).toEqual([]);
  });
});
