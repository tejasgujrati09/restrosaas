import { getSession, markEnded } from "./session";

const CONFIGURED_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
// In development the API shares the page's host, so the same build works on localhost and, with
// LAN=1 scripts/dev.sh, from a phone on the LAN. Production always uses the configured URL.
const API_URL =
  process.env.NODE_ENV !== "production" && typeof window !== "undefined" && /^https?:\/\/(localhost|\d+\.\d+\.\d+\.\d+)[:/]/.test(CONFIGURED_API_URL)
    ? CONFIGURED_API_URL.replace(/^(https?:\/\/)[^:/]+/, `$1${window.location.hostname}`)
    : CONFIGURED_API_URL;

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
  }
}

type Options = {
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  /** Reuse one key across retries of the same tap, so a double tap or a retry cannot order twice. */
  idempotencyKey?: string;
  /** The QR landing sends the current token (or none) explicitly. */
  token?: string | null;
  /** Do not treat a 401 as "your visit has ended" (used by the landing). */
  landing?: boolean;
  /** Internal: this call is already the retry after learning a moved tab. */
  retried?: boolean;
};

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {};
  const token = options.token !== undefined ? options.token : (getSession()?.token ?? null);
  if (token) headers.Authorization = `Bearer ${token}`;
  if (method !== "GET") headers["Idempotency-Key"] = options.idempotencyKey ?? crypto.randomUUID();
  let body: string | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  const response = await fetch(`${API_URL}${path}`, { method, headers, body });
  if (response.ok) return (await response.json()) as T;

  let payload: { code?: string; message?: string; details?: Record<string, unknown> } = {};
  try {
    payload = await response.json();
  } catch {
    // non-JSON error body; fall through with generic values
  }
  if (response.status === 403 && !options.retried && path.includes("/tabs/")) {
    // A waiter may have merged our tab into another, so the id we stored is stale. Ask which
    // tab we are on now and, if it changed, repeat the request against the new one.
    const before = getSession()?.tab_id;
    const { refreshTab } = await import("./live");
    await refreshTab().catch(() => {});
    const after = getSession()?.tab_id;
    if (before && after && before !== after) {
      return api<T>(path.replace(before, after), { ...options, retried: true });
    }
  }
  if (response.status === 401 && !options.landing) markEnded();
  throw new ApiError(
    response.status,
    payload.code ?? `http_${response.status}`,
    payload.message ?? "Something went wrong. Try again.",
    payload.details,
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Could not reach the server. Check your connection and try again.";
}

/** A failure worth retrying with the same idempotency key: no answer, or a server error. */
export function isRetryable(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status >= 500;
}
