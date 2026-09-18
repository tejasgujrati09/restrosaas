import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage, isRetryable } from "./api";
import { stubBrowser } from "./test-env";

function reply(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

beforeEach(() => {
  vi.unstubAllGlobals();
  const { storage } = stubBrowser();
  storage.set("restosaas.guest", JSON.stringify({ token: "r.secret", tab_id: "t", qr_token: "qr" }));
  vi.stubGlobal("crypto", { randomUUID: () => "generated-key" });
});
afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("sends the session token and a generated idempotency key on writes", async () => {
    const fetch = reply(200, { ok: true });
    vi.stubGlobal("fetch", fetch);
    await api("/v1/x", { method: "POST", body: { a: 1 } });
    const init = fetch.mock.calls[0]?.[1] as RequestInit;
    expect(init.headers).toMatchObject({
      Authorization: "Bearer r.secret",
      "Idempotency-Key": "generated-key",
      "Content-Type": "application/json",
    });
  });

  it("reuses the caller's key so a retry cannot order twice", async () => {
    const fetch = reply(200, {});
    vi.stubGlobal("fetch", fetch);
    await api("/v1/x", { method: "POST", body: {}, idempotencyKey: "same" });
    expect((fetch.mock.calls[0]?.[1] as RequestInit).headers).toMatchObject({ "Idempotency-Key": "same" });
  });

  it("sends no key on reads and no token when told to send none", async () => {
    const fetch = reply(200, {});
    vi.stubGlobal("fetch", fetch);
    await api("/v1/x", { token: null });
    const headers = (fetch.mock.calls[0]?.[1] as RequestInit).headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBeUndefined();
    expect(headers.Authorization).toBeUndefined();
  });

  it("turns an error body into an ApiError with its stable code", async () => {
    vi.stubGlobal("fetch", reply(409, { code: "awaiting_waiter", message: "Wait." }));
    await expect(api("/v1/x")).rejects.toMatchObject({ status: 409, code: "awaiting_waiter", message: "Wait." });
  });

  it("marks the session ended on 401, except from the landing", async () => {
    vi.stubGlobal("fetch", reply(401, { code: "session_ended", message: "Over." }));
    await expect(api("/v1/x")).rejects.toBeInstanceOf(ApiError);
    const { getSession } = await import("./session");
    expect(getSession()?.ended).toBe(true);
  });

  it("does not end the session when the landing itself gets a 401", async () => {
    vi.stubGlobal("fetch", reply(401, { code: "x", message: "y" }));
    await expect(api("/v1/x", { landing: true })).rejects.toBeInstanceOf(ApiError);
    const { getSession } = await import("./session");
    expect(getSession()?.ended).toBeUndefined();
  });

  it("copes with a non-JSON error body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 502 })));
    await expect(api("/v1/x")).rejects.toMatchObject({ status: 502, code: "http_502" });
  });
});

describe("failure handling", () => {
  it("retries with the same key only when there was no definite answer", () => {
    expect(isRetryable(new TypeError("network"))).toBe(true);
    expect(isRetryable(new ApiError(503, "x", "y"))).toBe(true);
    expect(isRetryable(new ApiError(409, "item_unavailable", "y"))).toBe(false);
    expect(isRetryable(new ApiError(422, "validation_error", "y"))).toBe(false);
  });

  it("shows the server's words, or a connection hint", () => {
    expect(errorMessage(new ApiError(409, "x", "That item is sold out."))).toBe("That item is sold out.");
    expect(errorMessage(new TypeError("Failed to fetch"))).toMatch(/connection/);
  });
});
