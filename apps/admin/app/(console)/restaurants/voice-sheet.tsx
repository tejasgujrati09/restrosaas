"use client";

import { useEffect, useState } from "react";
import { Badge, ErrorBanner, Sheet, Skeleton, Stepper } from "@restosaas/ui";
import { api } from "@/lib/api";
import type { PlatformRestaurant, PlatformVoice } from "@/lib/types";
import { useAction, useResource } from "@/lib/use-resource";
import { allowanceCopy, isInFlight, phaseView, stepLabel } from "@/lib/voice";

/** A restaurant's Voice Orders: whether it may use them at all (admin's call), and how the
 *  owner's setup is going, with the internal detail that owners never see. */
export function VoiceSheet({
  restaurant,
  onClose,
  onChanged,
}: {
  restaurant: PlatformRestaurant | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const path = restaurant ? `/v1/platform/restaurants/${restaurant.id}/voice` : null;
  const voice = useResource<PlatformVoice>(path);
  const action = useAction();
  const [confirmStop, setConfirmStop] = useState(false);

  const running = voice.data?.outlets.some((o) => isInFlight(o.phase)) ?? false;
  const { reload } = voice;
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(reload, 3_000);
    return () => window.clearInterval(timer);
  }, [running, reload]);

  function close() {
    setConfirmStop(false);
    action.clearError();
    onClose();
  }

  async function setAllowed(allowed: boolean) {
    if (!restaurant) return;
    const done = await action.run(() =>
      api(`/v1/platform/restaurants/${restaurant.id}/voice-orders`, { method: "PUT", body: { allowed } }),
    );
    if (done) {
      setConfirmStop(false);
      voice.reload();
      onChanged();
    }
  }

  async function retry(outletId: string) {
    if (!restaurant) return;
    if (await action.run(() => api(`/v1/platform/restaurants/${restaurant.id}/voice/${outletId}/retry`, { method: "POST" }))) {
      voice.reload();
    }
  }

  const allowed = voice.data?.allowed ?? false;
  const copy = allowanceCopy(allowed);
  return (
    <Sheet open={restaurant !== null} onClose={close} title={restaurant ? `Voice Orders · ${restaurant.brand_name}` : ""}>
      <ErrorBanner message={action.error ?? voice.error} />
      {!voice.data && !voice.error ? <Skeleton what="voice orders" lines={3} block /> : null}
      {voice.data ? (
        <>
          <h3>Voice Orders</h3>
          <p>
            <strong>{copy.headline}</strong>
          </p>
          <p className="muted">{copy.body}</p>
          {allowed ? (
            confirmStop ? (
              <>
                <p className="muted">
                  The owner&apos;s voice agent stops taking new calls. Someone already on a call can finish their order, and nothing is deleted.
                </p>
                <div className="stack">
                  <button type="button" className="danger-solid btn-lg" disabled={action.busy} onClick={() => setAllowed(false)}>
                    Disable voice orders
                  </button>
                  <button type="button" className="secondary btn-lg" onClick={() => setConfirmStop(false)}>
                    Keep enabled
                  </button>
                </div>
              </>
            ) : (
              <button type="button" className="danger" onClick={() => setConfirmStop(true)}>
                Disable voice orders…
              </button>
            )
          ) : (
            <button type="button" className="btn-lg" disabled={action.busy} onClick={() => setAllowed(true)}>
              Enable voice orders
            </button>
          )}

          {voice.data.outlets.map((o) => {
            const view = phaseView(o.phase);
            return (
              <section key={o.outlet_id} className="voice-outlet" aria-label={`${o.outlet_name} voice setup`}>
                <h3>{o.outlet_name}</h3>
                <p className="inline">
                  <Badge tone={view.tone}>{view.label}</Badge>
                  {!allowed && o.phase === "unavailable" ? <span className="muted">Owner cannot switch it on</span> : null}
                </p>
                {o.phone_number ? <p>Phone number: {o.phone_number}</p> : null}
                {o.agent_id ? <p className="muted">Agent id: {o.agent_id}</p> : null}
                {o.steps.length > 0 ? <Stepper steps={o.steps} /> : null}
                {o.message ? <p role="alert">{o.message}</p> : null}
                {o.detail ? <p className="muted">Detail: {o.detail}</p> : null}
                {o.can_retry ? (
                  <button type="button" disabled={action.busy} onClick={() => retry(o.outlet_id)}>
                    Retry provisioning
                  </button>
                ) : null}
                {o.attempts.length > 0 ? (
                  <details>
                    <summary>Attempts ({o.attempts.length})</summary>
                    <ol className="attempts">
                      {o.attempts.map((a, i) => (
                        <li key={i}>
                          {new Date(a.started_at).toLocaleString()} · {a.kind === "enable" ? "Set up" : "Turn off"} ·{" "}
                          {a.outcome ?? "in progress"}
                          {a.failed_step ? ` at ${stepLabel(a.failed_step)}` : ""}
                          {a.requested_by_platform_admin ? " · by admin" : ""}
                          {a.error ? <span className="muted"> · {a.error}</span> : null}
                        </li>
                      ))}
                    </ol>
                  </details>
                ) : null}
              </section>
            );
          })}
        </>
      ) : null}
    </Sheet>
  );
}
