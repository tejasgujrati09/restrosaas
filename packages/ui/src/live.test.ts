import { beforeEach, describe, expect, it, vi } from "vitest";
import { CLOSE_TAB_ENDED, CLOSE_TAB_MOVED, CLOSE_UNAUTHORISED, LiveConnection, type LiveDeps } from "./live";

class FakeSocket {
  sent: string[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor(public url: string) {}
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
  }
  receive(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

let sockets: FakeSocket[];
let timers: { fn: () => void; ms: number }[];
let ended: number;
let conn: LiveConnection;

beforeEach(() => {
  sockets = [];
  timers = [];
  ended = 0;
  const deps: LiveDeps = {
    open: (url) => {
      const s = new FakeSocket(url);
      sockets.push(s);
      return s;
    },
    setTimer: (fn, ms) => {
      timers.push({ fn, ms });
      return timers.length;
    },
    clearTimer: vi.fn(),
    random: () => 1,
  };
  conn = new LiveConnection(deps, { onEnded: () => (ended += 1) });
});

const session = { token: "r.secret", url: "ws://localhost:8000/v1/outlets/out-1/ws" };

describe("live connection", () => {
  it("authenticates in the first frame, not the URL", () => {
    conn.start(session);
    const s = sockets[0]!;
    expect(s.url).toBe("ws://localhost:8000/v1/outlets/out-1/ws");
    expect(s.url).not.toContain("secret");
    s.onopen?.();
    expect(JSON.parse(s.sent[0]!)).toEqual({ type: "auth", token: "r.secret", last_event_id: null });
  });

  it("is connected once the server says ready, and bumps so screens refetch", () => {
    conn.start(session);
    const before = conn.getState().tick;
    sockets[0]!.receive({ type: "ready" });
    expect(conn.getState()).toEqual({ tick: before + 1, connected: true });
  });

  it("bumps on every event and on resync, but not on pings", () => {
    conn.start(session);
    const s = sockets[0]!;
    s.receive({ type: "ready" });
    const t = conn.getState().tick;
    s.receive({ type: "ping" });
    expect(conn.getState().tick).toBe(t);
    s.receive({ type: "event", id: 7 });
    s.receive({ type: "resync" });
    expect(conn.getState().tick).toBe(t + 2);
  });

  it("ignores frames that are not JSON", () => {
    conn.start(session);
    sockets[0]!.onmessage?.({ data: "not json" });
    expect(conn.getState().tick).toBe(0);
  });

  it("reconnects with backoff and resumes from the last event it saw", () => {
    conn.start(session);
    sockets[0]!.receive({ type: "event", id: 5 });
    sockets[0]!.receive({ type: "event", id: 3 });
    sockets[0]!.onclose?.({ code: 1006 });
    expect(conn.getState().connected).toBe(false);
    expect(timers[0]!.ms).toBe(1000);
    timers[0]!.fn();
    sockets[1]!.onopen?.();
    expect(JSON.parse(sockets[1]!.sent[0]!).last_event_id).toBe(5);
    // Still failing: the wait doubles, up to a cap.
    sockets[1]!.onclose?.({ code: 1006 });
    expect(timers[1]!.ms).toBe(2000);
    for (let i = 0; i < 8; i++) {
      timers.at(-1)!.fn();
      sockets.at(-1)!.onclose?.({ code: 1006 });
    }
    expect(timers.at(-1)!.ms).toBe(30_000);
  });

  it("starts the backoff over after a successful connection", () => {
    conn.start(session);
    sockets[0]!.onclose?.({ code: 1006 });
    timers[0]!.fn();
    sockets[1]!.receive({ type: "ready" });
    sockets[1]!.onclose?.({ code: 1006 });
    expect(timers[1]!.ms).toBe(1000);
  });

  it("jitters the wait so a Wi-Fi blip does not reconnect every phone at once", () => {
    const opened: FakeSocket[] = [];
    const waits: number[] = [];
    const jittery = new LiveConnection({
      open: (url) => {
        const s = new FakeSocket(url);
        opened.push(s);
        return s;
      },
      setTimer: (_fn, ms) => waits.push(ms),
      clearTimer: () => {},
      random: () => 0,
    });
    jittery.start(session);
    opened[0]!.onclose?.({ code: 1006 });
    expect(waits).toEqual([500]);
  });

  it.each([CLOSE_UNAUTHORISED, CLOSE_TAB_ENDED])("stops for good on close code %i and says the session ended", (code) => {
    conn.start(session);
    sockets[0]!.onclose?.({ code });
    expect(ended).toBe(1);
    expect(timers).toHaveLength(0);
  });

  it("bumps on signals such as menu_changed", () => {
    conn.start(session);
    sockets[0]!.receive({ type: "ready" });
    const t = conn.getState().tick;
    sockets[0]!.receive({ type: "signal", name: "menu_changed" });
    expect(conn.getState().tick).toBe(t + 1);
  });

  it("on a moved tab, waits for the app to learn the new one, then reconnects from scratch", async () => {
    let learned = false;
    const moved = new LiveConnection(
      {
        open: (url) => {
          const s = new FakeSocket(url);
          sockets.push(s);
          return s;
        },
        setTimer: () => 0,
        clearTimer: () => {},
        random: () => 1,
      },
      { onMoved: async () => void (learned = true) },
    );
    moved.start(session);
    sockets[0]!.receive({ type: "event", id: 9 });
    sockets[0]!.onclose?.({ code: CLOSE_TAB_MOVED });
    await vi.waitFor(() => expect(sockets).toHaveLength(2));
    expect(learned).toBe(true);
    sockets[1]!.onopen?.();
    expect(JSON.parse(sockets[1]!.sent[0]!).last_event_id).toBeNull();
  });

  it("stop() closes the socket and cancels a pending reconnect", () => {
    conn.start(session);
    sockets[0]!.onclose?.({ code: 1006 });
    conn.stop();
    timers[0]!.fn();
    expect(sockets).toHaveLength(1);
    conn.start(session);
    const s = sockets[1]!;
    conn.stop();
    expect(s.closed).toBe(true);
    expect(conn.getState().connected).toBe(false);
  });

  it("notifies subscribers, and not after they leave", () => {
    const listener = vi.fn();
    const off = conn.subscribe(listener);
    conn.start(session);
    sockets[0]!.receive({ type: "event", id: 1 });
    expect(listener).toHaveBeenCalled();
    listener.mockClear();
    off();
    sockets[0]!.receive({ type: "event", id: 2 });
    expect(listener).not.toHaveBeenCalled();
  });
});
