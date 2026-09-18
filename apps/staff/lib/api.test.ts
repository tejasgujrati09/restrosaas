import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const store = new Map<string, string>();

beforeEach(() => {
  store.clear();
  vi.stubGlobal("window", {
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
    location: { replace: vi.fn() },
  });
});
afterEach(() => vi.unstubAllGlobals());

function respond(status: number, body?: unknown) {
  return vi.fn(async () => new Response(body === undefined ? null : JSON.stringify(body), { status }));
}

describe("api", () => {
  it("sends the bearer token and no idempotency key on GET", async () => {
    store.set("restosaas.token", "tok");
    const fetchMock = respond(200, { ok: true });
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("./api");
    await api("/v1/x");
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.headers).toMatchObject({ Authorization: "Bearer tok" });
    expect(init.headers).not.toHaveProperty("Idempotency-Key");
  });

  it("adds a fresh idempotency key to every write and honours an explicit one", async () => {
    const fetchMock = respond(201, { id: "1" });
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("./api");
    await api("/v1/x", { method: "POST", body: { a: 1 } });
    await api("/v1/x", { method: "POST", body: { a: 1 } });
    await api("/v1/x", { method: "POST", body: { a: 1 }, idempotencyKey: "fixed" });
    const keys = fetchMock.mock.calls.map(
      (c) => ((c as unknown as [string, RequestInit])[1].headers as Record<string, string>)["Idempotency-Key"],
    );
    expect(keys[0]).not.toBe(keys[1]);
    expect(keys[2]).toBe("fixed");
  });

  it("turns API errors into ApiError with the stable code", async () => {
    vi.stubGlobal("fetch", respond(409, { code: "duplicate", message: "That already exists." }));
    const { api, ApiError, errorMessage } = await import("./api");
    const error = await api("/v1/x", { method: "POST", body: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "duplicate" });
    expect(errorMessage(error)).toBe("That already exists.");
  });

  it("clears the session and redirects on 401", async () => {
    store.set("restosaas.token", "stale");
    vi.stubGlobal("fetch", respond(401, { code: "invalid_token", message: "Sign in again." }));
    const { api } = await import("./api");
    await api("/v1/x").catch(() => undefined);
    expect(store.has("restosaas.token")).toBe(false);
    expect((window.location.replace as ReturnType<typeof vi.fn>).mock.calls[0]).toEqual(["/login"]);
  });

  it("does not redirect on a 401 from an unauthenticated call such as a wrong OTP", async () => {
    vi.stubGlobal("fetch", respond(401, { code: "invalid_otp", message: "Wrong code." }));
    const { api } = await import("./api");
    await api("/v1/auth/otp/verify", { method: "POST", body: {}, authenticated: false }).catch(() => undefined);
    expect((window.location.replace as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(0);
  });

  it("returns undefined for 204 and a friendly message when the network is down", async () => {
    vi.stubGlobal("fetch", respond(204));
    const { api, errorMessage } = await import("./api");
    expect(await api("/v1/x", { method: "DELETE" })).toBeUndefined();
    expect(errorMessage(new TypeError("Failed to fetch"))).toMatch(/connection/);
  });
});
