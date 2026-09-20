"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { Badge, Card, EmptyState, Notice, PageHeader, Skeleton, type Tone } from "@restosaas/ui";
import { ErrorBanner } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import type { VoiceAgent } from "@/lib/types";

const STATUS: Record<string, { tone: Tone; label: string }> = {
  off: { tone: "neutral", label: "Off" },
  pending: { tone: "info", label: "Setting up" },
  active: { tone: "ok", label: "On" },
  disabled: { tone: "neutral", label: "Paused" },
  failed: { tone: "danger", label: "Needs attention" },
};

/** The owner turns the phone assistant on or off. It reads this restaurant's own menu, answers
 *  calls to a phone number, and sends each order to Phone orders for someone to accept. */
export default function VoiceOrderingPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}/voice-agent`;
  const agent = useResource<VoiceAgent>(base);
  const action = useAction();
  const [confirmOff, setConfirmOff] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  if (!agent.data) return agent.error ? <ErrorBanner message={agent.error} /> : <Skeleton what="voice ordering" lines={3} block />;

  const a = agent.data;
  const status = STATUS[a.status] ?? { tone: "neutral" as Tone, label: a.status };

  async function call(path: string, done: string) {
    setNote(null);
    if (await action.run(() => api<VoiceAgent>(`${base}/${path}`, { method: "POST" }))) {
      setNote(done);
      setConfirmOff(false);
      agent.reload();
    }
  }

  return (
    <>
      <PageHeader
        title="Voice ordering"
        subtitle="Let customers order by phone. An assistant answers, takes the order and sends it to you to accept."
      />
      <ErrorBanner message={action.error} />
      {note ? <Notice tone="info">{note}</Notice> : null}
      <Card title="Status">
        <p className="inline">
          <Badge tone={status.tone}>{status.label}</Badge>
          {a.phone_number ? (
            <span>
              Customers call <a href={`tel:${a.phone_number}`}>{a.phone_number}</a>
            </span>
          ) : null}
        </p>
        {a.last_error ? (
          <Notice tone="warn">
            Something went wrong: {a.last_error}. Try again. If it keeps happening, contact support.
          </Notice>
        ) : null}
        {a.status === "active" ? (
          confirmOff ? (
            <>
              <p>Customers who call will not be able to order. Turn voice ordering off?</p>
              <div className="inline">
                <button type="button" className="danger-solid" disabled={action.busy} onClick={() => call("disable", "Voice ordering is off.")}>
                  Yes, turn it off
                </button>
                <button type="button" className="secondary" disabled={action.busy} onClick={() => setConfirmOff(false)}>
                  Keep it on
                </button>
              </div>
            </>
          ) : (
            <div className="inline">
              <button type="button" className="secondary" disabled={action.busy} onClick={() => call("resync", "The assistant now has your current menu.")}>
                Update menu on the assistant
              </button>
              <button type="button" className="tertiary" disabled={action.busy} onClick={() => setConfirmOff(true)}>
                Turn off…
              </button>
            </div>
          )
        ) : (
          <button type="button" disabled={action.busy} onClick={() => call("enable", "Voice ordering is on.")}>
            {a.status === "failed" ? "Try again" : a.status === "disabled" ? "Turn voice ordering back on" : "Turn on voice ordering"}
          </button>
        )}
      </Card>
      {a.status === "off" ? (
        <EmptyState title="Not set up yet.">
          Turning it on creates the assistant from your menu and gives it a phone number. Only items that are on the menu and in stock are offered to callers.
        </EmptyState>
      ) : null}
      <Card title="How it works">
        <ol>
          <li>A customer calls. The assistant greets them and knows returning customers by their number.</li>
          <li>It only offers what is on your menu, at your prices, and asks for pickup or delivery.</li>
          <li>The order appears under Phone orders. The kitchen sees it only after you accept it.</li>
          <li>The assistant tells the caller the restaurant will confirm. Nothing is promised until you accept.</li>
        </ol>
        <p className="muted">After you change your menu, tap Update menu on the assistant so callers hear the new one.</p>
      </Card>
    </>
  );
}
