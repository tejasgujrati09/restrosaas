"use client";

import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Card, ErrorBanner, Field } from "@/components/ui";
import { useAction } from "@/components/hooks";
import { api } from "@/lib/api";
import { setToken } from "@/lib/session";

export default function InvitePage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const { busy, error, run } = useAction();

  async function sendCode() {
    if (await run(() => api("/v1/invites/otp", { method: "POST", body: { token }, authenticated: false }))) setSent(true);
  }

  async function accept(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const out = await api<{ access_token: string }>("/v1/invites/accept", {
        method: "POST",
        authenticated: false,
        body: { token, code, name: name || null },
      });
      setToken(out.access_token);
      router.replace("/");
    });
  }

  return (
    <main className="auth">
      <h1>Join your team</h1>
      <p className="muted">You were invited to work at a restaurant. Confirm your number to join.</p>
      <Card>
        {!sent ? (
          <>
            <p className="muted">We will send a code to the mobile number this invite was made for.</p>
            <ErrorBanner message={error} />
            <button type="button" disabled={busy} onClick={sendCode}>Send code</button>
          </>
        ) : (
          <form onSubmit={accept}>
            <Field label="Code"><input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} /></Field>
            <Field label="Your name"><input autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <ErrorBanner message={error} />
            <button type="submit" disabled={busy || code.length !== 6}>Join</button>
          </form>
        )}
      </Card>
    </main>
  );
}
