/** The staff screen's live socket: refetch on any push. A refused token (4401) means the
 * sign-in is no longer valid (deactivated, expired), so go back to the login. */
import { LiveConnection, type LiveState } from "@restosaas/ui/live";
import { useSyncExternalStore } from "react";
import { clearSession } from "./session";

export const live = new LiveConnection(undefined, {
  onEnded: () => {
    clearSession();
    window.location.replace("/login");
  },
});

const SERVER_STATE: LiveState = { tick: 0, connected: false };

export function useLive(): LiveState {
  return useSyncExternalStore(live.subscribe, live.getState, () => SERVER_STATE);
}

export function socketUrl(outletId: string): string {
  const configured = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const api =
    process.env.NODE_ENV !== "production" && typeof window !== "undefined" && /^https?:\/\/(localhost|\d+\.\d+\.\d+\.\d+)[:/]/.test(configured)
      ? configured.replace(/^(https?:\/\/)[^:/]+/, `$1${window.location.hostname}`)
      : configured;
  return `${api.replace(/^http/, "ws")}/v1/outlets/${outletId}/ws`;
}
