import { vi } from "vitest";

/** A minimal browser: localStorage plus window events, enough for the stores. */
export function stubBrowser(): { storage: Map<string, string> } {
  const storage = new Map<string, string>();
  const target = new EventTarget();
  vi.stubGlobal("window", {
    localStorage: {
      getItem: (k: string) => storage.get(k) ?? null,
      setItem: (k: string, v: string) => void storage.set(k, v),
      removeItem: (k: string) => void storage.delete(k),
    },
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    dispatchEvent: target.dispatchEvent.bind(target),
  });
  return { storage };
}
