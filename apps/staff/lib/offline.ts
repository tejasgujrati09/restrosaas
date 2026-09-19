"use client";

import { useSyncExternalStore } from "react";
import { api, ApiError } from "./api";
import { live } from "./live";
import { ActionQueue, IndexedDbStore, MemoryStore, Refused, type QueueState, type QueuedAction } from "./offline-queue";

function makeStore() {
  return typeof indexedDB === "undefined" ? new MemoryStore() : new IndexedDbStore();
}

async function send(action: QueuedAction): Promise<void> {
  try {
    await api(action.path, { method: action.method, body: action.body, idempotencyKey: action.id });
  } catch (e) {
    // Only an answer from the server is a refusal; anything else (no network) is retried.
    if (e instanceof ApiError) throw new Refused(e.status, e.message);
    throw e;
  }
}

export const queue = new ActionQueue(makeStore(), send);

/** A failure that just means "no connection right now", so the action should wait, not fail. */
export function isOffline(e: unknown): boolean {
  return !(e instanceof ApiError) || e.status === 502 || e.status === 503 || e.status === 504;
}

/**
 * Do something now, or, if there is no connection, keep it and do it when there is.
 * Resolves "queued" when it was kept. The action's id is its Idempotency-Key, so a
 * retry after a lost answer cannot apply it twice.
 */
export async function act(method: "POST" | "PUT", path: string, body: unknown, label: string): Promise<"sent" | "queued"> {
  const id = crypto.randomUUID();
  try {
    await api(path, { method, body, idempotencyKey: id });
    return "sent";
  } catch (e) {
    if (!isOffline(e)) throw e;
    await queue.enqueue({ id, method, path, body, label });
    return "queued";
  }
}

let started = false;

/** Loads what a previous session left and keeps trying while anything is waiting. */
export function startOfflineSync(): void {
  if (started || typeof window === "undefined") return;
  started = true;
  void queue.load().then(() => queue.flush());
  window.addEventListener("online", () => void queue.flush());
  live.subscribe(() => {
    if (live.getState().connected && queue.getState().pending.length > 0) void queue.flush();
  });
  window.setInterval(() => {
    if (queue.getState().pending.length > 0) void queue.flush();
  }, 15_000);
}

const SERVER: QueueState = { pending: [], failed: [], flushing: false, synced: 0 };

export function useOffline(): QueueState {
  return useSyncExternalStore(queue.subscribe, queue.getState, () => SERVER);
}
