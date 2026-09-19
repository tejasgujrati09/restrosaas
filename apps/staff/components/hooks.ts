"use client";

import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useLive } from "@/lib/live";

/**
 * `live` refetches whenever the server pushes a change and, with `pollMs`, polls far less
 * often while the socket is up (the poll is then only a safety net).
 */
export function useResource<T>(path: string | null, pollMs?: number, live = false) {
  const { tick: liveTick, connected } = useLive();
  const pushed = live ? liveTick : 0;
  const interval = pollMs && live && connected ? pollMs * 8 : pollMs;
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
    if (!interval) {
      return () => {
        cancelled = true;
      };
    }
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, interval);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [path, tick, interval, pushed]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, reload, loading: data === null && error === null };
}

/** Runs a user action once at a time, with a busy flag and a message to show on failure. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (action: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await action();
      return true;
    } catch (e) {
      setError(errorMessage(e));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);
  /** Like `run`, but hands back the action's result (undefined on failure). */
  const call = useCallback(async <R,>(action: () => Promise<R>): Promise<R | undefined> => {
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
  return { busy, error, run, call, clearError: () => setError(null) };
}
