"use client";

import { toast } from "@restosaas/ui";
import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "./api";

/** Loads `path` once and again whenever `reload` is called. `null` path means "not yet". */
export function useResource<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let cancelled = false;
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
    return () => {
      cancelled = true;
    };
  }, [path, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, reload };
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
  return { busy, error, run, clearError: () => setError(null) };
}
