"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ErrorBanner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { getSession, setSession } from "@/lib/session";
import type { QrSession } from "@/lib/types";

/** The QR landing: trade the table's token for a TabSession, then go to the menu. */
export default function Landing() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const started = useRef(-1);

  useEffect(() => {
    if (started.current === attempt) return;
    started.current = attempt;
    // Send the current session, if any, so rescanning the same table reuses it.
    const existing = getSession();
    api<QrSession>(`/v1/qr/${encodeURIComponent(token)}/session`, {
      method: "POST",
      body: {},
      token: existing && !existing.ended ? existing.token : null,
      landing: true,
    })
      .then((body) => {
        const sessionToken = body.session_token ?? (existing && !existing.ended ? existing.token : null);
        if (!sessionToken) throw new Error("no session");
        setSession({
          token: sessionToken,
          expires_at: body.expires_at,
          outlet_id: body.outlet_id,
          outlet_name: body.outlet_name,
          table_label: body.table_label,
          tab_id: body.tab_id,
          qr_token: token,
        });
        router.replace("/menu");
      })
      .catch((e: unknown) => setError(errorMessage(e)));
  }, [token, attempt, router]);

  return (
    <main className="center">
      {error ? (
        <>
          <h1>We couldn&apos;t open your table</h1>
          <ErrorBanner message={error} />
          <button
            type="button"
            className="btn-lg"
            onClick={() => {
              setError(null);
              setAttempt((n) => n + 1);
            }}
          >
            Try again
          </button>
        </>
      ) : (
        <>
          <span className="spinner" aria-hidden="true" />
          <h1>Opening your table…</h1>
          <p className="muted" role="status">
            One moment.
          </p>
        </>
      )}
    </main>
  );
}
