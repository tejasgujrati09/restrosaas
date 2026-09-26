"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Badge, EmptyState, formatBp, formatInr, PageHeader, parsePercentToBp, parseRupees, Skeleton } from "@restosaas/ui";
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
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"all" | "category" | "item">("all");
  const [target, setTarget] = useState("");
  const [type, setType] = useState<"percent_off" | "fixed">("percent_off");
  const [value, setValue] = useState("");
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4, 5, 6]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
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
    <div className="narrow">
      <PageHeader
        title="Offers"
        subtitle="Happy hours, event pricing and other special prices. A guest is charged the price at the moment they order, and it stays that price on their bill even after the window ends. Times are in your outlet's timezone. A window that runs past midnight belongs to the day it starts."
      />
      <Card title="Current offers">
        <ErrorBanner message={rules.error} onRetry={rules.reload} />
        {!rules.data && !rules.error ? <Skeleton what="your offers" lines={3} /> : null}
        {rules.data?.length === 0 ? <EmptyState title="No offers yet">Add an offer below and guests will see the lower price while it runs.</EmptyState> : null}
        <ul className="list">
          {rules.data?.map((r) => (
            <li key={r.id}>
              <span><strong>{r.name}</strong> — {describe(r)} {!r.active ? <Badge tone="danger">Off</Badge> : null}</span>
              <button type="button" className="danger" onClick={() => action.run(async () => { await api(`${base}/price-rules/${r.id}`, { method: "DELETE" }); rules.reload(); })}>Delete</button>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Add an offer">
        <form onSubmit={add}>
          <div className="row">
            <Field label="Name"><input required value={name} placeholder="e.g. Happy hour" onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Applies to">
              <select value={scope} onChange={(e) => { setScope(e.target.value as typeof scope); setTarget(""); }}>
                <option value="all">Everything</option><option value="category">One category</option><option value="item">One item</option>
              </select>
            </Field>
            <Field label={scope === "item" ? "Which item" : "Which category"}>
              <select required={scope !== "all"} disabled={scope === "all"} value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="">{scope === "all" ? "Not needed" : "Choose…"}</option>
                {scope === "category" ? menu.data?.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>) : null}
                {scope === "item" ? items.map((i) => <option key={i.id} value={i.id}>{i.name}</option>) : null}
              </select>
            </Field>
          </div>
          <div className="row">
            <Field label="Discount type">
              <select value={type} onChange={(e) => setType(e.target.value as typeof type)}>
                <option value="percent_off">Percent off</option><option value="fixed">Fixed price</option>
              </select>
            </Field>
            <Field label={type === "percent_off" ? "Percent off" : "Price (₹)"} size="short"><input required inputMode="decimal" value={value} placeholder={type === "percent_off" ? "e.g. 20" : "e.g. 199"} onChange={(e) => setValue(e.target.value)} /></Field>
          </div>
          <div className="row">
            <Field label="From" size="short" hint="For example 17:00"><input type="time" required value={start} onChange={(e) => setStart(e.target.value)} /></Field>
            <Field label="Until" size="short" hint="For example 20:00"><input type="time" required value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
          </div>
          <fieldset className="field">
            <legend className="field-label">Days</legend>
            <div className="inline">
              {DAYS.map((d, i) => (
                <label key={d} className="check"><input type="checkbox" checked={days.includes(i)} onChange={(e) => setDays(e.target.checked ? [...days, i] : days.filter((x) => x !== i))} /> {d}</label>
              ))}
            </div>
          </fieldset>
          <ErrorBanner message={inputError} />
          <button type="submit" disabled={action.busy || days.length === 0}>Add offer</button>
        </form>
      </Card>
    </div>
  );
}
