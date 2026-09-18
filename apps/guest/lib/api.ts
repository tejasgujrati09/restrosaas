import { getSession, markEnded } from "./session";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
