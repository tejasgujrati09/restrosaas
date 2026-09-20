import { useSyncExternalStore } from "react";

/** The platform token lives in localStorage so a reload keeps the admin signed in. It is a
 *  different key from the staff app's, and a different kind of token: neither works in the other. */
const KEY = "restosaas.platform.token";
const listeners = new Set<() => void>();

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  window.localStorage.setItem(KEY, token);
  listeners.forEach((l) => l());
}

export function clearSession(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // storage blocked: nothing to clear
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/** The token, or null while hydrating or signed out. */
export function useToken(): string | null {
  return useSyncExternalStore(subscribe, getToken, () => null);
}
