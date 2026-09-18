"use client";

import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "./api";

/** Loads `path` and, if `pollMs` is set, refreshes while the page is visible. */
export function useResource<T>(path: string | null, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    const load = () =>
      api<T>(path)
        .then((value) => {
          if (!cancelled) {
            setData(value);
            setError(null);
          }
        })
        .catch((e: unknown) => {
          if (!cancelled) setError(errorMessage(e));
        });
    void load();
    if (!pollMs) return () => void (cancelled = true);
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, pollMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [path, pollMs, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, reload, loading: data === null && error === null };
}

/** One action at a time, with a busy flag and a message to show on failure. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <R,>(action: () => Promise<R>): Promise<R | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await action();
    } catch (e) {
      setError(errorMessage(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run };
}
