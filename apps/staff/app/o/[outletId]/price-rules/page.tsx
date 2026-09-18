"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { formatBp, formatInr, parsePercentToBp, parseRupees } from "@restosaas/ui";
import { Card, ErrorBanner, Field } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import type { Menu, PriceRule, PriceRuleIn } from "@/lib/types";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function describe(rule: PriceRule): string {
  const what = rule.rule_type === "percent_off" ? `${formatBp(rule.value)}% off` : `${formatInr(rule.value)} each`;
  const days = rule.days_of_week.length === 7 ? "every day" : rule.days_of_week.map((d) => DAYS[d]).join(", ");
  return `${what}, ${rule.start_time.slice(0, 5)}–${rule.end_time.slice(0, 5)}, ${days}`;
}

export default function PriceRulesPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}`;
  const rules = useResource<PriceRule[]>(`${base}/price-rules`);
  const menu = useResource<Menu>(`${base}/menu`);
  const [name, setName] = useState("Happy hour");
  const [scope, setScope] = useState<"all" | "category" | "item">("all");
  const [target, setTarget] = useState("");
  const [type, setType] = useState<"percent_off" | "fixed">("percent_off");
  const [value, setValue] = useState("");
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4, 5, 6]);
  const [start, setStart] = useState("17:00");
  const [end, setEnd] = useState("20:00");
  const [inputError, setInputError] = useState<string | null>(null);
  const action = useAction();

  async function add(event: FormEvent) {
    event.preventDefault();
    const parsed = type === "percent_off" ? parsePercentToBp(value) : parseRupees(value);
    if (parsed === null) { setInputError(type === "percent_off" ? "Enter a percentage like 20 or 12.5." : "Enter a price in rupees, like 199."); return; }
    setInputError(null);
    const body: PriceRuleIn = {
      name, scope, target_id: scope === "all" ? null : target || null, rule_type: type, value: parsed,
      days_of_week: days, start_time: `${start}:00`, end_time: `${end}:00`, active: true,
    };
    if (await action.run(() => api(`${base}/price-rules`, { method: "POST", body }))) { rules.reload(); setValue(""); }
  }

  const items = menu.data?.categories.flatMap((c) => c.items) ?? [];

  return (
    <>
      <h1>Happy hours and event pricing</h1>
      <p className="muted">A guest is charged the price at the moment they order, and it stays that price on their bill even after the window ends. Times are in your outlet&apos;s timezone. A window that runs past midnight belongs to the day it starts.</p>
      <Card title="Current rules">
        <ErrorBanner message={rules.error} />
        {rules.data?.length === 0 ? <p>No rules yet.</p> : null}
        <ul>
          {rules.data?.map((r) => (
            <li key={r.id} className="inline">
              <strong>{r.name}</strong> — {describe(r)} {!r.active ? <span className="badge off">Off</span> : null}
              <button type="button" className="danger" onClick={() => action.run(async () => { await api(`${base}/price-rules/${r.id}`, { method: "DELETE" }); rules.reload(); })}>Delete</button>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Add a rule">
        <form onSubmit={add}>
          <div className="row">
            <Field label="Name"><input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Applies to">
              <select value={scope} onChange={(e) => { setScope(e.target.value as typeof scope); setTarget(""); }}>
                <option value="all">Everything</option><option value="category">One category</option><option value="item">One item</option>
              </select>
            </Field>
            {scope === "category" ? (
              <Field label="Category"><select required value={target} onChange={(e) => setTarget(e.target.value)}><option value="" />{menu.data?.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
            ) : null}
            {scope === "item" ? (
              <Field label="Item"><select required value={target} onChange={(e) => setTarget(e.target.value)}><option value="" />{items.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</select></Field>
            ) : null}
          </div>
          <div className="row">
            <Field label="Discount type">
              <select value={type} onChange={(e) => setType(e.target.value as typeof type)}>
                <option value="percent_off">Percent off</option><option value="fixed">Fixed price</option>
              </select>
            </Field>
            <Field label={type === "percent_off" ? "Percent off" : "Price (₹)"}><input required inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} /></Field>
            <Field label="From"><input type="time" required value={start} onChange={(e) => setStart(e.target.value)} /></Field>
            <Field label="Until"><input type="time" required value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
          </div>
          <fieldset className="field">
            <legend className="field-label">Days</legend>
            <div className="inline">
              {DAYS.map((d, i) => (
                <label key={d} className="check"><input type="checkbox" checked={days.includes(i)} onChange={(e) => setDays(e.target.checked ? [...days, i] : days.filter((x) => x !== i))} /> {d}</label>
              ))}
            </div>
          </fieldset>
          <ErrorBanner message={inputError ?? action.error} />
          <button type="submit" disabled={action.busy || days.length === 0}>Add rule</button>
        </form>
      </Card>
    </>
  );
}
