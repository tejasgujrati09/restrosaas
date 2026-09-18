/**
 * One WebSocket per guest session. The socket is a signal, not a data channel: any event
 * (or a reconnect) bumps `tick`, and screens refetch what they show over REST. The server
 * replays what was missed from the last event id we saw, and a dropped or blocked socket
 * costs nothing but freshness, because screens keep polling, more slowly, while it is up.
 */
import { useSyncExternalStore } from "react";
import { markEnded, type GuestSession } from "./session";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const CLOSE_UNAUTHORISED = 4401;
export const CLOSE_TAB_ENDED = 4410;

export type LiveState = { tick: number; connected: boolean };

type SocketLike = {
  send(data: string): void;
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number }) => void) | null;
};

export type LiveDeps = {
  open: (url: string) => SocketLike;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
  random: () => number;
};

const browserDeps: LiveDeps = {
  open: (url) => new WebSocket(url) as unknown as SocketLike,
  setTimer: (fn, ms) => window.setTimeout(fn, ms),
  clearTimer: (handle) => window.clearTimeout(handle as number),
  random: Math.random,
};

const MAX_BACKOFF_MS = 30_000;

export class LiveConnection {
  private state: LiveState = { tick: 0, connected: false };
  private listeners = new Set<() => void>();
  private socket: SocketLike | null = null;
  private timer: unknown = null;
  private lastEventId: number | null = null;
  private attempt = 0;
  private running = false;
  private session: Pick<GuestSession, "token" | "outlet_id"> | null = null;

  constructor(
    private deps: LiveDeps = browserDeps,
    private onEnded: () => void = () => {},
  ) {}

  getState = (): LiveState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  start(session: Pick<GuestSession, "token" | "outlet_id">): void {
    this.stop();
    this.session = session;
    this.running = true;
    this.lastEventId = null;
    this.attempt = 0;
    this.connect();
  }

  stop(): void {
    this.running = false;
    if (this.timer !== null) this.deps.clearTimer(this.timer);
    this.timer = null;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onopen = socket.onmessage = socket.onclose = null;
      socket.close();
    }
    this.set({ connected: false });
  }

  private set(patch: Partial<LiveState>): void {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((l) => l());
  }

  private bump(patch: Partial<LiveState> = {}): void {
    this.set({ ...patch, tick: this.state.tick + 1 });
  }

  private connect(): void {
    const session = this.session;
    if (!this.running || !session) return;
    const socket = this.deps.open(`${API_URL.replace(/^http/, "ws")}/v1/outlets/${session.outlet_id}/ws`);
    this.socket = socket;
    socket.onopen = () => {
      // The token goes in the first frame, never the URL, so it stays out of access logs.
      socket.send(JSON.stringify({ type: "auth", token: session.token, last_event_id: this.lastEventId }));
    };
    socket.onmessage = (event) => {
      let message: { type?: string; id?: number };
      try {
        message = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if (message.type === "ready") {
        this.attempt = 0;
        this.bump({ connected: true });
      } else if (message.type === "event" || message.type === "resync") {
        if (typeof message.id === "number") this.lastEventId = Math.max(this.lastEventId ?? 0, message.id);
        this.bump();
      }
    };
    socket.onclose = (event) => {
      this.socket = null;
      this.set({ connected: false });
      if (event.code === CLOSE_UNAUTHORISED || event.code === CLOSE_TAB_ENDED) {
        // Not a network problem: the session is over. Do not hammer the server.
        this.running = false;
        this.onEnded();
        return;
      }
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (!this.running) return;
    const base = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.attempt);
    this.attempt += 1;
    // Jitter so a Wi-Fi blip does not reconnect every phone in the room at once.
    this.timer = this.deps.setTimer(() => this.connect(), base * (0.5 + this.deps.random() / 2));
  }
}

export const live = new LiveConnection(undefined, markEnded);

const SERVER_STATE: LiveState = { tick: 0, connected: false };

export function useLive(): LiveState {
  return useSyncExternalStore(live.subscribe, live.getState, () => SERVER_STATE);
}
