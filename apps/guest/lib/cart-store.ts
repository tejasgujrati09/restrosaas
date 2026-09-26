/** The cart is per tab and survives reloads. It holds choices only (ids, quantities, notes);
 * prices always come from the API's cart quote. */
import { useSyncExternalStore } from "react";

export type CartEntry = {
  key: string;
  menu_item_id: string;
  name: string;
  qty: number;
  modifier_ids: string[];
  note: string;
};

const EVENT = "restosaas.cart.changed";
const cache = new Map<string, { raw: string | null; value: CartEntry[] }>();
const EMPTY: CartEntry[] = [];

function storageKey(tabId: string): string {
  return `restosaas.cart.${tabId}`;
}

export function readCart(tabId: string): CartEntry[] {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(storageKey(tabId));
  } catch {
    return EMPTY;
  }
  const hit = cache.get(tabId);
  if (hit && hit.raw === raw) return hit.value;
  let value = EMPTY;
  try {
    value = raw ? (JSON.parse(raw) as CartEntry[]) : EMPTY;
  } catch {
    value = EMPTY;
  }
  cache.set(tabId, { raw, value });
  return value;
}

export function writeCart(tabId: string, entries: CartEntry[]): void {
  try {
    if (entries.length) window.localStorage.setItem(storageKey(tabId), JSON.stringify(entries));
    else window.localStorage.removeItem(storageKey(tabId));
  } catch {
    // storage unavailable: the cart is lost on reload, which is acceptable
  }
  window.dispatchEvent(new Event(EVENT));
}

export function addToCart(tabId: string, entry: Omit<CartEntry, "key">): void {
  const current = readCart(tabId);
  const same = current.find(
    (e) =>
      e.menu_item_id === entry.menu_item_id &&
      e.note === entry.note &&
      [...e.modifier_ids].sort().join() === [...entry.modifier_ids].sort().join(),
  );
  if (same) {
    writeCart(
      tabId,
      current.map((e) => (e.key === same.key ? { ...e, qty: Math.min(50, e.qty + entry.qty) } : e)),
    );
  } else {
    writeCart(tabId, [...current, { ...entry, key: crypto.randomUUID() }]);
  }
}

export function setQty(tabId: string, key: string, qty: number): void {
  const current = readCart(tabId);
  writeCart(
    tabId,
    qty < 1 ? current.filter((e) => e.key !== key) : current.map((e) => (e.key === key ? { ...e, qty: Math.min(50, qty) } : e)),
  );
}

/** The kitchen instruction for one cart line ("less spicy"). Trimmed and capped like the server. */
export function setNote(tabId: string, key: string, note: string): void {
  const clean = note.trim().slice(0, 200);
  writeCart(
    tabId,
    readCart(tabId).map((e) => (e.key === key ? { ...e, note: clean } : e)),
  );
}

function subscribe(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}

export function useCart(tabId: string | null): CartEntry[] {
  return useSyncExternalStore(
    subscribe,
    () => (tabId ? readCart(tabId) : EMPTY),
    () => EMPTY,
  );
}
