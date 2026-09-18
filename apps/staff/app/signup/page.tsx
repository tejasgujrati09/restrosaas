"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Card, ErrorBanner, Field } from "@/components/ui";
import { useAction } from "@/components/hooks";
import { api } from "@/lib/api";
import { toE164 } from "@/lib/phone";
import { setToken } from "@/lib/session";
import { STATES } from "@/lib/states";

export default function SignupPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    phone: "", code: "", owner_name: "", legal_name: "", brand_name: "", outlet_name: "", state_code: "29",
  });
  const [sent, setSent] = useState(false);
  const { busy, error, run } = useAction();
  const e164 = toE164(form.phone);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  async function requestCode() {
    if (!e164) return;
    if (await run(() => api("/v1/signup/otp", { method: "POST", body: { phone: e164 }, authenticated: false }))) {
      setSent(true);
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const out = await api<{ access_token: string; outlet_id: string }>("/v1/signup", {
        method: "POST",
        authenticated: false,
        body: {
          phone: e164,
          code: form.code,
          owner_name: form.owner_name || null,
          legal_name: form.legal_name,
          brand_name: form.brand_name,
          outlet_name: form.outlet_name,
          state_code: form.state_code,
        },
      });
      setToken(out.access_token);
      router.replace(`/o/${out.outlet_id}/setup`);
    });
  }

  return (
    <main>
      <h1>Create your restaurant</h1>
      <Card>
        <form onSubmit={create}>
          <Field label="Your mobile number" hint="You will sign in with this number.">
            <input inputMode="tel" autoComplete="tel" value={form.phone} onChange={set("phone")} disabled={sent} />
          </Field>
          {!sent ? (
            <button type="button" disabled={busy || !e164} onClick={requestCode}>Send code</button>
          ) : (
            <>
              <Field label="Code from your phone">
                <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={form.code} onChange={set("code")} />
              </Field>
              <Field label="Your name"><input autoComplete="name" value={form.owner_name} onChange={set("owner_name")} /></Field>
              <Field label="Registered business name" hint="As on your GST registration.">
                <input required value={form.legal_name} onChange={set("legal_name")} />
              </Field>
              <Field label="Restaurant name" hint="What guests see.">
                <input required value={form.brand_name} onChange={set("brand_name")} />
              </Field>
              <Field label="Outlet name" hint="For example: Indiranagar">
                <input required value={form.outlet_name} onChange={set("outlet_name")} />
              </Field>
              <Field label="State">
                <select value={form.state_code} onChange={set("state_code")}>
                  {STATES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
                </select>
              </Field>
              <ErrorBanner message={error} />
              <button type="submit" disabled={busy || form.code.length !== 6}>Create restaurant</button>
            </>
          )}
          {!sent ? <ErrorBanner message={error} /> : null}
        </form>
      </Card>
      <p>Already have an account? <Link href="/login">Sign in</Link></p>
    </main>
  );
}
