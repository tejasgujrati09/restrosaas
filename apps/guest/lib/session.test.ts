import { beforeEach, describe, expect, it, vi } from "vitest";
import { stubBrowser } from "./test-env";

const session = {
  token: "r.s",
  expires_at: "2026-09-18T20:00:00Z",
  outlet_id: "o",
  outlet_name: "Bar",
  table_label: "T1",
  tab_id: "t",
  qr_token: "qr",
};

// The module caches the parsed value, so each test gets a fresh copy.
async function load() {
  vi.resetModules();
  return import("./session");
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("guest session", () => {
  it("is null before a scan", async () => {
    stubBrowser();
    const { getSession } = await load();
    expect(getSession()).toBeNull();
  });

  it("round-trips and returns the same object until it changes", async () => {
    stubBrowser();
    const { getSession, setSession } = await load();
    setSession(session);
    expect(getSession()).toEqual(session);
    expect(getSession()).toBe(getSession());
  });

  it("marks the session ended but keeps the QR token for starting again", async () => {
    stubBrowser();
    const { getSession, setSession, markEnded } = await load();
    setSession(session);
    markEnded();
    expect(getSession()).toMatchObject({ ended: true, qr_token: "qr" });
    markEnded();
    expect(getSession()?.ended).toBe(true);
  });

  it("ignores corrupt storage", async () => {
    const { storage } = stubBrowser();
    storage.set("restosaas.guest", "{nope");
    const { getSession, markEnded } = await load();
    expect(getSession()).toBeNull();
    expect(() => markEnded()).not.toThrow();
  });

  it("copes with storage being unavailable", async () => {
    stubBrowser();
    const { getSession, setSession } = await load();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: () => {
          throw new Error("blocked");
        },
        setItem: () => {
          throw new Error("blocked");
        },
      },
      dispatchEvent: () => true,
    });
    expect(getSession()).toBeNull();
    expect(() => setSession(session)).not.toThrow();
  });
});
