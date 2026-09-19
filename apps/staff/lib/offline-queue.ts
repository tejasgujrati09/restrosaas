/**
 * Actions taken while the connection is down, kept on the device and replayed in order when
 * it returns (docs/SPEC.md §4: the staff app tolerates a few minutes without Wi-Fi).
 *
 * Every action carries its own idempotency key (its `id`), so replaying one whose first
 * attempt reached the server but whose answer was lost does nothing twice. Nothing is
 * dropped silently: an action the server refuses, or one that waited too long to be safe to
 * apply blind, moves to `failed` where the staff member can retry or discard it.
 */

export const STALE_AFTER_MS = 5 * 60_000;

export type QueuedAction = {
  /** Also the Idempotency-Key. */
  id: string;
  method: "POST" | "PUT";
  path: string;
  body: unknown;
  /** Plain words for the banner, e.g. "Serve round 2 at T4". */
  label: string;
  queuedAt: number;
  attempts: number;
};

export type FailedAction = QueuedAction & {
  reason: string;
  /** True when it only waited too long; "send anyway" is offered. */
  stale: boolean;
};

export interface QueueStore {
  pending(): Promise<QueuedAction[]>;
  failed(): Promise<FailedAction[]>;
  putPending(action: QueuedAction): Promise<void>;
  removePending(id: string): Promise<void>;
  putFailed(action: FailedAction): Promise<void>;
  removeFailed(id: string): Promise<void>;
}

/** What sending an action can do: succeed, or throw. `refused` means the server answered no. */
export type Sender = (action: QueuedAction) => Promise<void>;
export class Refused extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export type QueueState = {
  pending: QueuedAction[];
  failed: FailedAction[];
  flushing: boolean;
  /** How many actions have been sent so far; screens refetch when it changes. */
  synced: number;
};

/** A refusal is definite only for these: everything else (offline, 5xx, throttled) will be retried. */
function isDefinite(e: unknown): e is Refused {
  return e instanceof Refused && e.status >= 400 && e.status < 500 && e.status !== 401 && e.status !== 408 && e.status !== 429;
}

export class ActionQueue {
  private state: QueueState = { pending: [], failed: [], flushing: false, synced: 0 };
  private listeners = new Set<() => void>();
  private running: Promise<void> | null = null;

  constructor(
    private store: QueueStore,
    private send: Sender,
    private now: () => number = Date.now,
  ) {}

  getState = (): QueueState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private set(patch: Partial<QueueState>): void {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((l) => l());
  }

  /** Loads what a previous session left behind. */
  async load(): Promise<void> {
    this.set({ pending: await this.store.pending(), failed: await this.store.failed() });
  }

  async enqueue(action: Omit<QueuedAction, "queuedAt" | "attempts">): Promise<void> {
    const queued: QueuedAction = { ...action, queuedAt: this.now(), attempts: 0 };
    await this.store.putPending(queued);
    this.set({ pending: [...this.state.pending, queued] });
  }

  /** Sends what is waiting, oldest first, stopping at the first thing that cannot be sent yet. */
  flush(): Promise<void> {
    this.running ??= this.run().finally(() => {
      this.running = null;
      this.set({ flushing: false });
    });
    return this.running;
  }

  private async run(): Promise<void> {
    this.set({ flushing: true });
    for (const action of [...this.state.pending].sort((a, b) => a.queuedAt - b.queuedAt)) {
      if (this.now() - action.queuedAt > STALE_AFTER_MS) {
        await this.fail(action, "This waited more than 5 minutes, so it needs a look before it is sent.", true);
        continue;
      }
      try {
        await this.send(action);
      } catch (e) {
        if (isDefinite(e)) {
          await this.fail(action, e.message, false);
          continue;
        }
        const tried = { ...action, attempts: action.attempts + 1 };
        await this.store.putPending(tried);
        this.set({ pending: this.state.pending.map((p) => (p.id === action.id ? tried : p)) });
        return; // still offline (or the server is struggling): keep the rest in order
      }
      await this.store.removePending(action.id);
      this.set({
        pending: this.state.pending.filter((p) => p.id !== action.id),
        synced: this.state.synced + 1,
      });
    }
  }

  private async fail(action: QueuedAction, reason: string, stale: boolean): Promise<void> {
    const failed: FailedAction = { ...action, reason, stale };
    await this.store.putFailed(failed);
    await this.store.removePending(action.id);
    this.set({
      pending: this.state.pending.filter((p) => p.id !== action.id),
      failed: [...this.state.failed, failed],
    });
  }

  /** Puts a failed action back at the end of the queue (with a fresh clock) and tries again. */
  async retry(id: string): Promise<void> {
    const failed = this.state.failed.find((f) => f.id === id);
    if (!failed) return;
    await this.store.removeFailed(id);
    this.set({ failed: this.state.failed.filter((f) => f.id !== id) });
    await this.enqueue({ id: failed.id, method: failed.method, path: failed.path, body: failed.body, label: failed.label });
    await this.flush();
  }

  async discard(id: string): Promise<void> {
    await this.store.removeFailed(id);
    this.set({ failed: this.state.failed.filter((f) => f.id !== id) });
  }
}

export class MemoryStore implements QueueStore {
  private p = new Map<string, QueuedAction>();
  private f = new Map<string, FailedAction>();
  pending = async () => [...this.p.values()];
  failed = async () => [...this.f.values()];
  putPending = async (a: QueuedAction) => void this.p.set(a.id, a);
  removePending = async (id: string) => void this.p.delete(id);
  putFailed = async (a: FailedAction) => void this.f.set(a.id, a);
  removeFailed = async (id: string) => void this.f.delete(id);
}

function wrap<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/** The real thing, on IndexedDB, so a reload or a crash does not lose what is waiting. */
export class IndexedDbStore implements QueueStore {
  private db: Promise<IDBDatabase> | null = null;

  private open(): Promise<IDBDatabase> {
    this.db ??= new Promise((resolve, reject) => {
      const request = indexedDB.open("restosaas-staff", 1);
      request.onupgradeneeded = () => {
        request.result.createObjectStore("pending", { keyPath: "id" });
        request.result.createObjectStore("failed", { keyPath: "id" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    return this.db;
  }

  private async store(name: "pending" | "failed", mode: IDBTransactionMode): Promise<IDBObjectStore> {
    return (await this.open()).transaction(name, mode).objectStore(name);
  }

  pending = async () => (await wrap((await this.store("pending", "readonly")).getAll())) as QueuedAction[];
  failed = async () => (await wrap((await this.store("failed", "readonly")).getAll())) as FailedAction[];
  putPending = async (a: QueuedAction) => void (await wrap((await this.store("pending", "readwrite")).put(a)));
  removePending = async (id: string) => void (await wrap((await this.store("pending", "readwrite")).delete(id)));
  putFailed = async (a: FailedAction) => void (await wrap((await this.store("failed", "readwrite")).put(a)));
  removeFailed = async (id: string) => void (await wrap((await this.store("failed", "readwrite")).delete(id)));
}
