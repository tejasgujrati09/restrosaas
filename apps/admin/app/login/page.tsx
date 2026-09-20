"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Card, ErrorBanner, Field } from "@restosaas/ui";
import { api } from "@/lib/api";
import { setToken } from "@/lib/session";
import { useAction } from "@/lib/use-resource";

/** Indian mobile numbers only for now: 10 digits, with or without +91. */
function toE164(input: string): string | null {
  const digits = input.replace(/\D/g, "");
  if (digits.length === 10) return `+91${digits}`;
  if (digits.length === 12 && digits.startsWith("91")) return `+${digits}`;
  return null;
}

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
    if (await run(() => api("/v1/platform/auth/otp/request", { method: "POST", body: { phone: e164 }, authenticated: false }))) {
      setSent(true);
    }
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const out = await api<{ access_token: string }>("/v1/platform/auth/otp/verify", {
        method: "POST",
        body: { phone: e164, code },
        authenticated: false,
      });
      setToken(out.access_token);
      router.replace("/restaurants");
    });
  }

  return (
    <main className="auth">
      <h1>Platform admin</h1>
      <p className="muted">For the people who run the platform. Restaurant staff sign in to their own app.</p>
      <Card>
        {!sent ? (
          <form onSubmit={requestCode}>
            <Field label="Mobile number" hint="We will send a code to this number.">
              <input
                inputMode="tel"
                autoComplete="tel"
                value={phone}
                onChange={(e) => {
                  setPhone(e.target.value);
                  clearError();
                }}
              />
            </Field>
            <ErrorBanner message={error} />
            <button type="submit" disabled={busy || !e164}>
              Send code
            </button>
          </form>
        ) : (
          <form onSubmit={verify}>
            <p className="muted">Enter the 6-digit code sent to {e164}.</p>
            <Field label="Code">
              <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
            <ErrorBanner message={error} />
            <button type="submit" disabled={busy || code.length !== 6}>
              Sign in
            </button>
            <button
              type="button"
              className="tertiary wide"
              onClick={() => {
                setSent(false);
                setCode("");
                clearError();
              }}
            >
              Change number
            </button>
          </form>
        )}
      </Card>
    </main>
  );
}
