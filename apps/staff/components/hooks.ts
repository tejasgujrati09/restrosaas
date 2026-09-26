"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "@restosaas/ui";
import { api, errorMessage } from "@/lib/api";
import { useLive } from "@/lib/live";
import { useOffline } from "@/lib/offline";

/**
 * `live` refetches whenever the server pushes a change and, with `pollMs`, polls far less
 * often while the socket is up (the poll is then only a safety net).
 */
export function useResource<T>(path: string | null, pollMs?: number | ((data: T | null) => number | undefined), live = false) {
  const { tick: liveTick, connected } = useLive();
  const { synced } = useOffline();
  // A queued action reaching the server changes what is on screen just like a push does.
  const pushed = live ? liveTick + synced : 0;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  // A function lets the screen ask more often while something it shows is still in flight.
  const base = typeof pollMs === "function" ? pollMs(data) : pollMs;
  const interval = base && live && connected ? base * 8 : base;

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

/** One action at a time, with a busy flag. A failure is shown as a toast (it floats, so the page
 *  does not move); pass `{ inline: true }` on sign-in style forms, where the message belongs next
 *  to the field and `error` carries it. */
export function useAction({ inline = false }: { inline?: boolean } = {}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fail = useCallback(
    (e: unknown) => {
      if (inline) setError(errorMessage(e));
      else toast.error(errorMessage(e));
    },
    [inline],
  );
  const run = useCallback(async (action: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await action();
      return true;
    } catch (e) {
      fail(e);
      return false;
    } finally {
      setBusy(false);
    }
  }, [fail]);
  /** Like `run`, but hands back the action's result (undefined on failure). */
  const call = useCallback(async <R,>(action: () => Promise<R>): Promise<R | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await action();
    } catch (e) {
      fail(e);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, [fail]);
  return { busy, error, run, call, clearError: () => setError(null) };
}
