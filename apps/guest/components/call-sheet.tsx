"use client";

import { Sheet } from "@restosaas/ui";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAction } from "@/lib/use-resource";
import type { ServiceRequestType } from "@/lib/types";
import { getSession } from "@/lib/session";

const CHOICES: { type: ServiceRequestType; label: string }[] = [
  { type: "water", label: "Water" },
  { type: "waiter", label: "Call waiter" },
  { type: "bill", label: "Bring the bill" },
];

/** Three choices only, so "Call waiter" never turns into a chat. */
export function CallSheet({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone?: () => void }) {
  const action = useAction();
  const [sent, setSent] = useState<string | null>(null);

  async function send(type: ServiceRequestType, label: string) {
    const session = getSession();
    if (!session) return;
    const done = await action.run(() =>
      api(`/v1/outlets/${session.outlet_id}/tabs/${session.tab_id}/service-requests`, {
        method: "POST",
        body: { type },
      }),
    );
    if (done !== undefined) {
      setSent(label);
      onDone?.();
    }
  }

  return (
    <Sheet
      open={open}
      onClose={() => {
        setSent(null);
        onClose();
      }}
      title="How can we help?"
    >
      {sent ? (
        <p role="status" className="ok">
          Done: {sent.toLowerCase()}. Someone will be with you shortly.
        </p>
      ) : (
        <div className="stack">
          {CHOICES.map((c) => (
            <button key={c.type} type="button" className="secondary wide" disabled={action.busy} onClick={() => send(c.type, c.label)}>
              {c.label}
            </button>
          ))}
        </div>
      )}
    </Sheet>
  );
}
