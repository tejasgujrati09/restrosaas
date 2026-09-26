import { clearSession, getToken } from "./session";

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
  ) {
    super(message);
  }
}

type Options = { method?: "GET" | "POST" | "PUT"; body?: unknown; authenticated?: boolean };

/** No Idempotency-Key here: the admin writes are idempotent by nature (setting a status a
 *  restaurant already has does nothing and logs nothing). */
export async function api<T = void>(path: string, options: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (options.authenticated !== false && token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (response.ok) return response.status === 202 || response.status === 204 ? (undefined as T) : ((await response.json()) as T);

  let payload: { code?: string; message?: string } = {};
  try {
    payload = await response.json();
  } catch {
    // non-JSON error body
  }
  if (response.status === 401 && options.authenticated !== false) {
    clearSession();
    window.location.replace("/login");
  }
  throw new ApiError(response.status, payload.code ?? `http_${response.status}`, payload.message ?? "Something went wrong. Try again.");
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof TypeError) return "Could not reach the server. Check your connection and try again.";
  return "Something went wrong. Try again.";
}
