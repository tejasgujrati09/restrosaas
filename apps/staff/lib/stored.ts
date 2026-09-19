"use client";

import { useSyncExternalStore } from "react";

const EVENT = "restosaas.stored.changed";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** A string kept in localStorage that re-renders when it changes; null on the server. */
export function useStored(key: string): [string | null, (value: string | null) => void] {
  const value = useSyncExternalStore(
    (listener) => {
      window.addEventListener(EVENT, listener);
      window.addEventListener("storage", listener);
      return () => {
        window.removeEventListener(EVENT, listener);
        window.removeEventListener("storage", listener);
      };
    },
    () => read(key),
    () => null,
  );
  return [
    value,
    (next) => {
      try {
        if (next === null) window.localStorage.removeItem(key);
        else window.localStorage.setItem(key, next);
      } catch {
        // storage unavailable: nothing to remember
      }
      window.dispatchEvent(new Event(EVENT));
    },
  ];
}
