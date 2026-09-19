"use client";

import { useEffect } from "react";
import { queue, startOfflineSync, useOffline } from "@/lib/offline";
import { useLive } from "@/lib/live";

/** A thin bar, never a blocker: what is waiting to be sent, and what needs a look. */
export function OfflineBanner() {
  const { pending, failed, flushing } = useOffline();
  const { connected } = useLive();
  useEffect(() => startOfflineSync(), []);

  if (pending.length === 0 && failed.length === 0) return null;
  return (
    <div className="offline" role="status">
      {pending.length > 0 ? (
        <p>
          {connected ? "Sending" : "Offline, reconnecting"}: {pending.length} action{pending.length === 1 ? "" : "s"} {flushing ? "being sent" : "waiting"}
          <span className="muted"> ({pending.map((p) => p.label).join("; ")})</span>
        </p>
      ) : null}
      {failed.map((f) => (
        <p key={f.id} className="warn">
          {f.label}: {f.reason}{" "}
          <button type="button" className="secondary" onClick={() => queue.retry(f.id)}>{f.stale ? "Send anyway" : "Try again"}</button>{" "}
          <button type="button" className="secondary" onClick={() => queue.discard(f.id)}>Discard</button>
        </p>
      ))}
    </div>
  );
}
