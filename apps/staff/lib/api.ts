import { clearSession, getToken } from "./session";

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
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** Raw body (e.g. CSV text) sent with `contentType` instead of JSON. */
  raw?: string;
  contentType?: string;
  /** Reuse a key across retries of the same user action. Generated per call otherwise. */
  idempotencyKey?: string;
  authenticated?: boolean;
};

async function send(path: string, options: Options): Promise<Response> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {};
  const token = getToken();
  if (options.authenticated !== false && token) headers.Authorization = `Bearer ${token}`;
  if (method !== "GET") {
    headers["Idempotency-Key"] = options.idempotencyKey ?? crypto.randomUUID();
  }
  let body: string | undefined;
  if (options.raw !== undefined) {
    headers["Content-Type"] = options.contentType ?? "text/csv";
    body = options.raw;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  const response = await fetch(`${API_URL}${path}`, { method, headers, body });
  if (response.ok) return response;

  let payload: { code?: string; message?: string; details?: Record<string, unknown> } = {};
  try {
    payload = await response.json();
  } catch {
    // non-JSON error body; fall through with generic values
  }
  if (response.status === 401 && options.authenticated !== false) {
    clearSession();
    window.location.replace("/login");
  }
  throw new ApiError(
    response.status,
    payload.code ?? `http_${response.status}`,
    payload.message ?? "Something went wrong. Try again.",
    payload.details,
  );
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const response = await send(path, options);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** For PDFs and CSV downloads, which need the bearer token a plain link cannot send. */
export async function apiBlob(path: string): Promise<Blob> {
  return (await send(path, {})).blob();
}

export async function openBlob(path: string, filename?: string): Promise<void> {
  const blob = await apiBlob(path);
  const url = URL.createObjectURL(blob);
  if (filename) {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  } else {
    window.open(url, "_blank");
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Could not reach the server. Check your connection and try again.";
}
