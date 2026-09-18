"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Card, ErrorBanner, Field } from "@/components/ui";
import { useAction } from "@/components/hooks";
import { api } from "@/lib/api";
import { toE164 } from "@/lib/phone";
import { setToken } from "@/lib/session";

export default function LoginPage() {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const { busy, error, run, clearError } = useAction();
  const e164 = toE164(phone);

  async function requestCode(event: FormEvent) {
    event.preventDefault();
    if (!e164) return;
    if (await run(() => api("/v1/auth/otp/request", { method: "POST", body: { phone: e164 }, authenticated: false }))) {
      setSent(true);
    }
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const out = await api<{ access_token: string }>("/v1/auth/otp/verify", {
        method: "POST",
        body: { phone: e164, code },
        authenticated: false,
      });
      setToken(out.access_token);
      router.replace("/");
    });
  }

  return (
    <main>
      <h1>Sign in</h1>
      <Card>
        {!sent ? (
          <form onSubmit={requestCode}>
            <Field label="Mobile number" hint="We will send a code to this number.">
              <input inputMode="tel" autoComplete="tel" value={phone} onChange={(e) => { setPhone(e.target.value); clearError(); }} />
            </Field>
            <ErrorBanner message={error} />
            <button type="submit" disabled={busy || !e164}>Send code</button>
          </form>
        ) : (
          <form onSubmit={verify}>
            <p>Enter the 6-digit code sent to {e164}.</p>
            <Field label="Code">
              <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
            <ErrorBanner message={error} />
            <div className="inline">
              <button type="submit" disabled={busy || code.length !== 6}>Sign in</button>
              <button type="button" className="secondary" onClick={() => { setSent(false); setCode(""); clearError(); }}>Change number</button>
            </div>
          </form>
        )}
      </Card>
      <p>New restaurant? <Link href="/signup">Create your account</Link></p>
    </main>
  );
}
