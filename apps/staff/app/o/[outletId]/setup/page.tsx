"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { formatBp, paiseToInput, parsePercentToBp, parseRupees } from "@restosaas/ui";
import { Card, ErrorBanner, Field } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import { STATES } from "@/lib/states";
import type { Menu, Settings } from "@/lib/types";

type Form = {
  legal_name: string; brand_name: string; gstin: string; outlet_name: string; address: string;
  state_code: string; timezone: string; liquor_licensed: boolean; liquor_vat: string;
  service_charge: string; prices_include_tax: boolean; ack_threshold: string;
  waiter_confirm_mode: boolean; liquor_approval_required: boolean; invoice_prefix: string;
};

function toForm(s: Settings): Form {
  return {
    legal_name: s.legal_name, brand_name: s.brand_name, gstin: s.gstin ?? "", outlet_name: s.outlet_name,
    address: s.address ?? "", state_code: s.state_code, timezone: s.timezone,
    liquor_licensed: s.liquor_licensed, liquor_vat: formatBp(s.liquor_vat_rate_bp),
    service_charge: formatBp(s.service_charge_bp), prices_include_tax: s.prices_include_tax,
    ack_threshold: paiseToInput(s.ack_threshold_paise), waiter_confirm_mode: s.waiter_confirm_mode,
    liquor_approval_required: s.liquor_approval_required, invoice_prefix: s.invoice_prefix,
  };
}

export default function SetupPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}`;
  const settings = useResource<Settings>(`${base}/settings`);
  const menu = useResource<Menu>(`${base}/menu`);
  if (!settings.data) return <ErrorBanner message={settings.error} />;
  return <SetupForm base={base} s={settings.data} reload={settings.reload} menu={menu} />;
}

function SetupForm({ base, s, reload, menu }: {
  base: string; s: Settings; reload: () => void; menu: ReturnType<typeof useResource<Menu>>;
}) {
  const [form, setForm] = useState<Form>(() => toForm(s));
  const [saved, setSaved] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
  const save = useAction();
  const set = <K extends keyof Form>(key: K, value: Form[K]) => { setForm({ ...form, [key]: value }); setSaved(false); };

  async function submit(event: FormEvent) {
    event.preventDefault();
    const vat = parsePercentToBp(form.liquor_vat || "0");
    const service = parsePercentToBp(form.service_charge || "0");
    const ack = parseRupees(form.ack_threshold || "0");
    if (vat === null || service === null || ack === null) {
      setInputError("Check the percentages and the amount. Use numbers like 5, 12.5 or 500.");
      return;
    }
    setInputError(null);
    const ok = await save.run(() =>
      api<Settings>(`${base}/settings`, {
        method: "PATCH",
        body: {
          legal_name: form.legal_name, brand_name: form.brand_name, gstin: form.gstin || null,
          outlet_name: form.outlet_name, address: form.address || null, state_code: form.state_code,
          timezone: form.timezone, liquor_licensed: form.liquor_licensed, liquor_vat_rate_bp: vat,
          service_charge_bp: service, prices_include_tax: form.prices_include_tax,
          ack_threshold_paise: ack, waiter_confirm_mode: form.waiter_confirm_mode,
          liquor_approval_required: form.liquor_approval_required, invoice_prefix: form.invoice_prefix,
        },
      }),
    );
    if (ok) { setSaved(true); reload(); }
  }

  return (
    <>
      <h1>Outlet setup</h1>
      <Card title="Before you go live">
        {s.ready_to_go_live ? (
          <p className="ok">All set. Your outlet is ready for guests.</p>
        ) : (
          <ul className="checklist">{s.go_live_blockers.map((b) => <li key={b}>{b}</li>)}</ul>
        )}
      </Card>

      <form onSubmit={submit}>
        <Card title="Business">
          <Field label="Registered business name"><input required value={form.legal_name} onChange={(e) => set("legal_name", e.target.value)} /></Field>
          <Field label="Restaurant name"><input required value={form.brand_name} onChange={(e) => set("brand_name", e.target.value)} /></Field>
          <Field label="GSTIN" hint="15 characters. The first two digits must match your state.">
            <input value={form.gstin} onChange={(e) => set("gstin", e.target.value.toUpperCase())} maxLength={15} />
          </Field>
        </Card>
        <Card title="Outlet">
          <Field label="Outlet name"><input required value={form.outlet_name} onChange={(e) => set("outlet_name", e.target.value)} /></Field>
          <Field label="Address"><textarea value={form.address} onChange={(e) => set("address", e.target.value)} /></Field>
          <div className="row">
            <Field label="State">
              <select value={form.state_code} onChange={(e) => set("state_code", e.target.value)}>
                {STATES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
              </select>
            </Field>
            <Field label="Timezone"><input value={form.timezone} onChange={(e) => set("timezone", e.target.value)} /></Field>
          </div>
        </Card>
        <Card title="Prices and tax">
          <fieldset className="field">
            <legend className="field-label">How are prices on your menu card written?</legend>
            <label className="check"><input type="radio" name="mode" checked={form.prices_include_tax} onChange={() => set("prices_include_tax", true)} /> Prices include taxes</label>
            <label className="check"><input type="radio" name="mode" checked={!form.prices_include_tax} onChange={() => set("prices_include_tax", false)} /> Taxes are added on top</label>
            <span className="hint">You cannot switch this once the menu has items, because every price would change meaning.</span>
          </fieldset>
          <label className="check"><input type="checkbox" checked={form.liquor_licensed} onChange={(e) => set("liquor_licensed", e.target.checked)} /> This outlet serves liquor</label>
          {form.liquor_licensed ? (
            <Field label="State VAT on liquor (%)"><input inputMode="decimal" value={form.liquor_vat} onChange={(e) => set("liquor_vat", e.target.value)} /></Field>
          ) : null}
          <Field label="Service charge (%)" hint="Guests can remove it. Leave 0 for none."><input inputMode="decimal" value={form.service_charge} onChange={(e) => set("service_charge", e.target.value)} /></Field>
        </Card>
        <Card title="Ordering">
          <label className="check"><input type="checkbox" checked={form.waiter_confirm_mode} onChange={(e) => set("waiter_confirm_mode", e.target.checked)} /> A waiter must confirm each table before guests can order</label>
          <label className="check"><input type="checkbox" checked={form.liquor_approval_required} onChange={(e) => set("liquor_approval_required", e.target.checked)} /> A manager must approve liquor</label>
          <Field label="Ask guests to confirm staff-added items costing this much or more (₹)" hint="Stops a waiter adding an item to a bill the guest did not order.">
            <input inputMode="decimal" value={form.ack_threshold} onChange={(e) => set("ack_threshold", e.target.value)} />
          </Field>
        </Card>
        <Card title="Invoices">
          <Field label="Invoice prefix" hint={`Next invoice: ${s.next_invoice_preview}. Change the prefix to start a new series, for example at the start of a financial year. The counter carries on.`}>
            <input value={form.invoice_prefix} maxLength={10} onChange={(e) => set("invoice_prefix", e.target.value)} />
          </Field>
        </Card>
        <ErrorBanner message={inputError ?? save.error} />
        <div className="inline">
          <button type="submit" disabled={save.busy}>Save</button>
          {saved ? <span role="status" className="ok">Saved</span> : null}
        </div>
      </form>

      <TaxClasses base={base} menu={menu} />
      <Stations base={base} menu={menu} />
    </>
  );
}

function TaxClasses({ base, menu }: { base: string; menu: ReturnType<typeof useResource<Menu>> }) {
  const [name, setName] = useState("");
  const [rate, setRate] = useState("5");
  const [liquor, setLiquor] = useState(false);
  const action = useAction();

  async function add(event: FormEvent) {
    event.preventDefault();
    const bp = liquor ? 0 : parsePercentToBp(rate);
    if (bp === null) return;
    if (await action.run(() => api(`${base}/tax-classes`, { method: "POST", body: { name, gst_rate_bp: bp, liquor_vat: liquor } }))) {
      setName(""); menu.reload();
    }
  }

  return (
    <Card title="Tax classes">
      <p className="muted">Food is charged GST, split equally into CGST and SGST. Liquor is charged state VAT and no GST. Each menu item uses one tax class.</p>
      <ul>
        {menu.data?.tax_classes.map((t) => (
          <li key={t.id} className="inline">
            {t.name} <span className="badge">{t.liquor_vat ? "Liquor VAT" : `GST ${formatBp(t.gst_rate_bp)}%`}</span>
            <button type="button" className="danger" onClick={() => action.run(async () => { await api(`${base}/tax-classes/${t.id}`, { method: "DELETE" }); menu.reload(); })}>Remove</button>
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="row">
        <Field label="Name"><input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Food 5%" /></Field>
        <Field label="GST (%)"><input inputMode="decimal" value={rate} disabled={liquor} onChange={(e) => setRate(e.target.value)} /></Field>
        <label className="check"><input type="checkbox" checked={liquor} onChange={(e) => setLiquor(e.target.checked)} /> Liquor (state VAT)</label>
        <button type="submit" disabled={action.busy}>Add tax class</button>
      </form>
      <ErrorBanner message={action.error} />
    </Card>
  );
}

function Stations({ base, menu }: { base: string; menu: ReturnType<typeof useResource<Menu>> }) {
  const [name, setName] = useState("");
  const action = useAction();
  return (
    <Card title="Stations">
      <p className="muted">Where an item is prepared, for example Kitchen or Bar.</p>
      <ul>
        {menu.data?.stations.map((st) => (
          <li key={st.id} className="inline">
            {st.name}
            <button type="button" className="danger" onClick={() => action.run(async () => { await api(`${base}/stations/${st.id}`, { method: "DELETE" }); menu.reload(); })}>Remove</button>
          </li>
        ))}
      </ul>
      <form className="row" onSubmit={async (e) => { e.preventDefault(); if (await action.run(() => api(`${base}/stations`, { method: "POST", body: { name } }))) { setName(""); menu.reload(); } }}>
        <Field label="Name"><input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <button type="submit" disabled={action.busy}>Add station</button>
      </form>
      <ErrorBanner message={action.error} />
    </Card>
  );
}
