/**
 * The TabSession lives in localStorage so a reload keeps the guest on their tab.
 * It authorises one tab for at most six hours; any script on this origin could
 * read it, so the app renders no untrusted HTML. `qr_token` is kept so an ended
 * session can offer "start again" without another scan.
 */
import { useSyncExternalStore } from "react";

const KEY = "restosaas.guest";
const EVENT = "restosaas.guest.changed";

export type GuestSession = {
  token: string;
  expires_at: string;
  outlet_id: string;
  outlet_name: string;
  table_label: string;
  tab_id: string;
  qr_token: string;
  /** Set when the API said the session is over (tab closed or expired). */
  ended?: boolean;
};

let cachedRaw: string | null = null;
let cachedValue: GuestSession | null = null;

export function getSession(): GuestSession | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
  if (raw === cachedRaw) return cachedValue;
  cachedRaw = raw;
  try {
    cachedValue = raw ? (JSON.parse(raw) as GuestSession) : null;
  } catch {
    cachedValue = null;
  }
  return cachedValue;
}

function write(session: GuestSession | null): void {
  try {
    if (session) window.localStorage.setItem(KEY, JSON.stringify(session));
    else window.localStorage.removeItem(KEY);
  } catch {
    // storage unavailable (private mode): the session lasts until the page closes
  }
  window.dispatchEvent(new Event(EVENT));
}

export function setSession(session: GuestSession): void {
  write(session);
}

export function markEnded(): void {
  const current = getSession();
  if (current && !current.ended) write({ ...current, ended: true });
}

function subscribe(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}

/** Null on the server and until hydration finishes; use `useHydrated` before redirecting. */
export function useSession(): GuestSession | null {
  return useSyncExternalStore(subscribe, getSession, () => null);
}

export function useHydrated(): boolean {
  return useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
}
