/**
 * The access token lives in localStorage so a reload keeps the owner signed in.
 * The trade-off is that any script running on this origin can read it; the app
 * therefore renders no untrusted HTML. The API never trusts what is decoded
 * here: claims are only used to decide which screens to show.
 */
const KEY = "restosaas.token";
const EVENT = "restosaas.session";

export type Claim = { restaurant_id: string; outlet_id: string; role: string };

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  window.localStorage.setItem(KEY, token);
  window.dispatchEvent(new Event(EVENT));
}

export function subscribeToSession(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}

export function clearSession(): void {
  try {
    window.localStorage.removeItem(KEY);
    window.dispatchEvent(new Event(EVENT));
  } catch {
    // storage unavailable: nothing to clear
  }
}

export function claimsOf(token: string | null): Claim[] {
  if (!token) return [];
  try {
    const payload = token.split(".")[1] ?? "";
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const parsed = JSON.parse(json) as { roles?: Claim[] };
    return parsed.roles ?? [];
  } catch {
    return [];
  }
}

export function rolesAt(token: string | null, outletId: string): string[] {
  return claimsOf(token)
    .filter((c) => c.outlet_id === outletId)
    .map((c) => c.role);
}
