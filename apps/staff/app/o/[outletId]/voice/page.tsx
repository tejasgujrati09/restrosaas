"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { Badge, Card, Notice, PageHeader, Skeleton, Stepper } from "@restosaas/ui";
import { ErrorBanner } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import { voicePollMs } from "@/lib/orders";
import type { VoiceAgent } from "@/lib/types";

/** The owner turns the phone assistant on or off. Turning it on is set up in the background:
 *  this page shows the steps as they happen and never shows a vendor's words or ids. */
export default function VoiceOrderingPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}/voice-agent`;
  const agent = useResource<VoiceAgent>(base, (v) => voicePollMs(v?.phase), true);
  const action = useAction();
  const [confirmOff, setConfirmOff] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const a = agent.data;
  if (!a) return agent.error ? <ErrorBanner message={agent.error} /> : <Skeleton what="voice ordering" lines={3} block />;

  async function call(path: string, done: string | null) {
    setNote(null);
    if (await action.run(() => api<VoiceAgent>(`${base}/${path}`, { method: "POST" }))) {
      setNote(done);
      setConfirmOff(false);
      agent.reload();
    }
  }

  const turnOffFailed = a.status === "deprovisioning_failed";

  return (
    <>
      <PageHeader
        title="Voice ordering"
        subtitle="Let customers order by phone. An assistant answers, takes the order and sends it to you to accept."
      />
      <ErrorBanner message={action.error ?? agent.error} />
      {note ? <Notice tone="info">{note}</Notice> : null}

      {a.phase === "unavailable" ? (
        <Card title="Voice ordering">
          <p className="inline">
            <Badge tone="neutral">Not available</Badge>
          </p>
          <p>Voice ordering is currently unavailable. Please contact your administrator.</p>
        </Card>
      ) : null}

      {a.phase === "off" ? (
        <Card title="Voice ordering">
          <p className="inline">
            <Badge tone="neutral">Off</Badge>
          </p>
          <p>
            Enable voice ordering for your restaurant. We set up the phone number and the assistant for you. Only items that are on the menu and in stock are offered to callers.
          </p>
          <button type="button" disabled={action.busy || !a.can_enable} onClick={() => call("enable", null)}>
            Turn on voice ordering
          </button>
        </Card>
      ) : null}

      {a.phase === "setting_up" ? (
        <Card title="Setting up voice ordering…">
          <p role="status">This takes a moment. You can leave this page; setup carries on.</p>
          <Stepper steps={a.steps} />
          <button type="button" className="tertiary" disabled={action.busy} onClick={() => call("disable", "Setup cancelled.")}>
            Cancel setup
          </button>
        </Card>
      ) : null}

      {a.phase === "active" ? (
        <Card title="Voice ordering is on">
          <p className="inline">
            <Badge tone="ok">Active</Badge>
          </p>
          <dl className="facts">
            <div>
              <dt>Phone number</dt>
              <dd>{a.phone_number ? <a href={`tel:${a.phone_number}`}>{a.phone_number}</a> : "Not available"}</dd>
            </div>
            <div>
              <dt>Voice agent</dt>
              <dd>Phone ordering assistant</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>● Active</dd>
            </div>
          </dl>
          {confirmOff ? (
            <>
              <p>Callers will no longer be able to order. Someone already on a call can still finish their order. Turn voice ordering off?</p>
              <div className="inline">
                <button type="button" className="danger-solid" disabled={action.busy} onClick={() => call("disable", null)}>
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
          )}
        </Card>
      ) : null}

      {a.phase === "failed" ? (
        <Card title={turnOffFailed ? "Voice ordering could not be turned off" : "Voice ordering setup failed"}>
          <p className="inline">
            <Badge tone="danger">Needs attention</Badge>
          </p>
          <p role="alert">{a.message ?? "We couldn't complete the setup."}</p>
          {a.steps.length > 0 ? <Stepper steps={a.steps} /> : null}
          <button
            type="button"
            disabled={action.busy || (!turnOffFailed && !a.can_enable)}
            onClick={() => call(turnOffFailed ? "disable" : "enable", null)}
          >
            Retry
          </button>
          <p className="muted">If it keeps failing, contact your administrator.</p>
        </Card>
      ) : null}

      {a.phase === "turning_off" ? (
        <Card title="Turning voice ordering off…">
          <p role="status">New calls have stopped. Anyone already on a call can finish their order.</p>
        </Card>
      ) : null}

      <Card title="How it works">
        <ol>
          <li>A customer calls. The assistant greets them and knows returning customers by their number.</li>
          <li>It only offers what is on your menu, at your prices, and asks for pickup or delivery.</li>
          <li>The order appears under Orders and Phone orders. The kitchen sees it only after you accept it.</li>
          <li>The assistant tells the caller the restaurant will confirm. Nothing is promised until you accept.</li>
        </ol>
        <p className="muted">After you change your menu, tap Update menu on the assistant so callers hear the new one.</p>
      </Card>
    </>
  );
}
