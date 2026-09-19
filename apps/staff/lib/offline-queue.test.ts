import { beforeEach, describe, expect, it, vi } from "vitest";
import { ActionQueue, MemoryStore, Refused, STALE_AFTER_MS, type QueuedAction } from "./offline-queue";

let clock: number;
let sent: string[];
let behaviour: (a: QueuedAction) => Promise<void>;
let store: MemoryStore;
let queue: ActionQueue;

const action = (id: string, label = id) => ({ id, method: "POST" as const, path: `/v1/x/${id}`, body: { id }, label });

beforeEach(() => {
  clock = 1_000_000;
  sent = [];
  behaviour = async () => {};
  store = new MemoryStore();
  queue = new ActionQueue(store, async (a) => {
    await behaviour(a);
    sent.push(a.id);
  }, () => clock);
});

describe("action queue", () => {
  it("sends everything in the order it was taken, then is empty", async () => {
    await queue.enqueue(action("a"));
    clock += 10;
    await queue.enqueue(action("b"));
    await queue.flush();
    expect(sent).toEqual(["a", "b"]);
    expect(queue.getState().pending).toEqual([]);
    expect(await store.pending()).toEqual([]);
  });

  it("stops at the first action that cannot be sent and keeps the rest, in order", async () => {
    behaviour = async (a) => {
      if (a.id === "a") throw new TypeError("Failed to fetch");
    };
    await queue.enqueue(action("a"));
    clock += 10;
    await queue.enqueue(action("b"));
    await queue.flush();
    expect(sent).toEqual([]);
    expect(queue.getState().pending.map((p) => [p.id, p.attempts])).toEqual([["a", 1], ["b", 0]]);
    behaviour = async () => {};
    await queue.flush();
    expect(sent).toEqual(["a", "b"]);
  });

  it("treats a server error or throttling as 'try again', not as a refusal", async () => {
    for (const status of [401, 408, 429, 500, 503]) {
      behaviour = async () => {
        throw new Refused(status, "later");
      };
      const q = new ActionQueue(new MemoryStore(), async (a) => behaviour(a), () => clock);
      await q.enqueue(action("x"));
      await q.flush();
      expect(q.getState().pending).toHaveLength(1);
      expect(q.getState().failed).toHaveLength(0);
    }
  });

  it("moves a definite refusal to failed, with the server's words, and carries on", async () => {
    behaviour = async (a) => {
      if (a.id === "a") throw new Refused(409, "That table's tab is closed.");
    };
    await queue.enqueue(action("a", "Add 2 Tikka to T1"));
    clock += 10;
    await queue.enqueue(action("b"));
    await queue.flush();
    expect(sent).toEqual(["b"]);
    expect(queue.getState().failed).toMatchObject([{ id: "a", reason: "That table's tab is closed.", stale: false, label: "Add 2 Tikka to T1" }]);
    expect(queue.getState().pending).toEqual([]);
    expect(await store.failed()).toHaveLength(1);
  });

  it("does not apply an action blind after five minutes, and offers to send it anyway", async () => {
    await queue.enqueue(action("old"));
    clock += STALE_AFTER_MS + 1;
    await queue.enqueue(action("fresh"));
    await queue.flush();
    expect(sent).toEqual(["fresh"]);
    expect(queue.getState().failed).toMatchObject([{ id: "old", stale: true }]);
    await queue.retry("old");
    expect(sent).toEqual(["fresh", "old"]);
    expect(queue.getState().failed).toEqual([]);
  });

  it("keeps the same idempotency key across retries", async () => {
    const keys: string[] = [];
    behaviour = async (a) => {
      keys.push(a.id);
      if (keys.length === 1) throw new TypeError("offline");
    };
    await queue.enqueue(action("k1"));
    await queue.flush();
    await queue.flush();
    expect(keys).toEqual(["k1", "k1"]);
  });

  it("retry re-queues a refused action and discard forgets it", async () => {
    behaviour = async () => {
      throw new Refused(422, "not valid");
    };
    await queue.enqueue(action("a"));
    await queue.flush();
    behaviour = async () => {};
    await queue.retry("a");
    expect(sent).toEqual(["a"]);
    behaviour = async () => {
      throw new Refused(422, "again");
    };
    await queue.enqueue(action("b"));
    await queue.flush();
    await queue.discard("b");
    expect(queue.getState().failed).toEqual([]);
    expect(await store.failed()).toEqual([]);
    await queue.retry("nope");
    await queue.discard("nope");
  });

  it("only runs one flush at a time", async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    behaviour = async () => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await Promise.resolve();
      inFlight -= 1;
    };
    await queue.enqueue(action("a"));
    await queue.enqueue(action("b"));
    await Promise.all([queue.flush(), queue.flush(), queue.flush()]);
    expect(maxInFlight).toBe(1);
    expect(sent).toEqual(["a", "b"]);
  });

  it("picks up what an earlier session left behind", async () => {
    await store.putPending({ ...action("left"), queuedAt: clock, attempts: 2 });
    await store.putFailed({ ...action("bad"), queuedAt: clock, attempts: 0, reason: "no", stale: false });
    await queue.load();
    expect(queue.getState().pending.map((p) => p.id)).toEqual(["left"]);
    expect(queue.getState().failed.map((p) => p.id)).toEqual(["bad"]);
    await queue.flush();
    expect(sent).toEqual(["left"]);
  });

  it("tells subscribers about changes and stops when they leave", async () => {
    const listener = vi.fn();
    const off = queue.subscribe(listener);
    await queue.enqueue(action("a"));
    expect(listener).toHaveBeenCalled();
    off();
    listener.mockClear();
    await queue.flush();
    expect(listener).not.toHaveBeenCalled();
  });

  it("reports flushing while it works", async () => {
    let during = false;
    behaviour = async () => {
      during = queue.getState().flushing;
    };
    await queue.enqueue(action("a"));
    await queue.flush();
    expect(during).toBe(true);
    expect(queue.getState().flushing).toBe(false);
  });
});
