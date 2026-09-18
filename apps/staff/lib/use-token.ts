"use client";

import { useSyncExternalStore } from "react";
import { getToken, subscribeToSession } from "./session";

/** The current access token; null on the server and while signed out. */
export function useToken(): string | null {
  return useSyncExternalStore(subscribeToSession, getToken, () => null);
}
