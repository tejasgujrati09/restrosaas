/** The guest's single live socket, and what to do when it says the tab moved or ended. */
import { LiveConnection, type LiveState } from "@restosaas/ui/live";
import { useSyncExternalStore } from "react";
import { api } from "./api";
import { getSession, markEnded, setSession } from "./session";
import type { GuestSessionInfo } from "./types";

/** After a waiter merges this table's tab into another, ask which tab we are on now. */
export async function refreshTab(): Promise<void> {
  const session = getSession();
  if (!session) return;
  const info = await api<GuestSessionInfo>(`/v1/outlets/${session.outlet_id}/guest/session`);
  if (info.tab_id !== session.tab_id) {
    setSession({ ...session, tab_id: info.tab_id, table_label: info.table_label ?? session.table_label });
  }
}

export const live = new LiveConnection(undefined, { onEnded: markEnded, onMoved: () => refreshTab().catch(() => {}) });

const SERVER_STATE: LiveState = { tick: 0, connected: false };

export function useLive(): LiveState {
  return useSyncExternalStore(live.subscribe, live.getState, () => SERVER_STATE);
}
