"use client";

import { toast } from "@restosaas/ui";
import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "./api";
import { useLive } from "./live";

/**
 * Loads `path` and, if `pollMs` is set, refreshes while the page is visible. With `live`,
 * it also refetches whenever the server pushes a change, and polls a lot less often while
 * the socket is up (the poll is only a safety net then).
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
    if (!interval) return () => void (cancelled = true);
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, interval);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [path, interval, tick, pushed]);

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
  const run = useCallback(async <R,>(action: () => Promise<R>): Promise<R | undefined> => {
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
  return { busy, error, run };
}
