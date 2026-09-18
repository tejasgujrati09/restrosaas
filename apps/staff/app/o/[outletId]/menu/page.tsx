"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { formatInr, paiseToInput, parseRupees } from "@restosaas/ui";
import { Card, ErrorBanner, Field } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api, openBlob } from "@/lib/api";
import { rolesAt, getToken } from "@/lib/session";
import type { Item, ItemIn, Menu, ModifierGroup } from "@/lib/types";
import { MenuImport } from "./menu-import";

export default function MenuPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}`;
  const menu = useResource<Menu>(`${base}/menu`);
  const roles = typeof window === "undefined" ? [] : rolesAt(getToken(), outletId);
  const canEdit = roles.includes("owner");
  const canToggle = canEdit || roles.includes("manager") || roles.includes("kitchen") || roles.includes("bar");
  const [editing, setEditing] = useState<string | null>(null);
  const [categoryName, setCategoryName] = useState("");
  const action = useAction();

  if (!menu.data) return <ErrorBanner message={menu.error} />;
  const m = menu.data;
  const taxName = (id: string) => m.tax_classes.find((t) => t.id === id)?.name ?? "?";

  async function addCategory(event: FormEvent) {
    event.preventDefault();
    if (await action.run(() => api(`${base}/categories`, { method: "POST", body: { name: categoryName, sort_order: m.categories.length } }))) {
      setCategoryName(""); menu.reload();
    }
  }

  return (
    <>
      <h1>Menu</h1>
      <p className="muted">
        {m.prices_include_tax ? "Prices include taxes." : "Taxes are added on top of these prices."} Prices are shown exactly as you enter them.
      </p>
      <div className="inline">
        <button type="button" className="secondary" onClick={() => action.run(() => openBlob(`${base}/menu.pdf`))}>Print menu (PDF)</button>
      </div>
      <ErrorBanner message={action.error} />

      {m.categories.length === 0 ? <Card><p>No menu yet. Add a category, then items, or import a CSV below.</p></Card> : null}
      {m.categories.map((c) => (
        <Card key={c.id} title={c.name}>
          {!c.visible ? <span className="badge off">Hidden from guests</span> : null}
          <table>
            <thead><tr><th>Item</th><th>Price</th><th>Tax class</th><th>Availability</th><th /></tr></thead>
            <tbody>
              {c.items.map((item) =>
                editing === item.id && canEdit ? (
                  <tr key={item.id}><td colSpan={5}>
                    <ItemForm base={base} menu={m} initial={item} onDone={() => { setEditing(null); menu.reload(); }} onCancel={() => setEditing(null)} />
                  </td></tr>
                ) : (
                  <tr key={item.id}>
                    <td>{item.veg_flag ? "●" : "▲"} {item.name}{item.is_liquor ? " (liquor)" : ""}</td>
                    <td>{formatInr(item.base_price_paise)}</td>
                    <td>{taxName(item.tax_class_id)}</td>
                    <td>
                      <button type="button" className="secondary" disabled={!canToggle} aria-pressed={!item.available}
                        onClick={() => action.run(async () => { await api(`${base}/items/${item.id}/availability`, { method: "PUT", body: { available: !item.available } }); menu.reload(); })}>
                        {item.available ? "Available" : "Sold out"}
                      </button>
                    </td>
                    <td className="inline">
                      {canEdit ? <button type="button" className="secondary" onClick={() => setEditing(item.id)}>Edit</button> : null}
                      {canEdit ? <button type="button" className="danger" onClick={() => action.run(async () => { await api(`${base}/items/${item.id}`, { method: "DELETE" }); menu.reload(); })}>Delete</button> : null}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
          {canEdit ? (
            <details>
              <summary>Add an item to {c.name}</summary>
              <ItemForm base={base} menu={m} categoryId={c.id} onDone={menu.reload} />
              <button type="button" className="danger" onClick={() => action.run(async () => { await api(`${base}/categories/${c.id}`, { method: "DELETE" }); menu.reload(); })}>Remove empty category</button>
            </details>
          ) : null}
        </Card>
      ))}

      {canEdit ? (
        <>
          <Card title="Add a category">
            <form className="row" onSubmit={addCategory}>
              <Field label="Name"><input required value={categoryName} onChange={(e) => setCategoryName(e.target.value)} placeholder="Starters" /></Field>
              <button type="submit" disabled={action.busy}>Add category</button>
            </form>
          </Card>
          <ModifierGroups base={base} groups={m.modifier_groups} reload={menu.reload} />
          <MenuImport base={base} reload={menu.reload} />
        </>
      ) : null}
    </>
  );
}

function ItemForm({ base, menu, initial, categoryId, onDone, onCancel }: {
  base: string; menu: Menu; initial?: Item; categoryId?: string; onDone: () => void; onCancel?: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [price, setPrice] = useState(initial ? paiseToInput(initial.base_price_paise) : "");
  const [taxClassId, setTaxClassId] = useState(initial?.tax_class_id ?? menu.tax_classes[0]?.id ?? "");
  const [stationId, setStationId] = useState(initial?.station_id ?? "");
  const [veg, setVeg] = useState(initial?.veg_flag ?? true);
  const [liquor, setLiquor] = useState(initial?.is_liquor ?? false);
  const [groups, setGroups] = useState<string[]>(initial?.modifier_group_ids ?? []);
  const [priceError, setPriceError] = useState<string | null>(null);
  const action = useAction();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const paise = parseRupees(price);
    if (paise === null) { setPriceError("Enter the price in rupees, like 120 or 120.50."); return; }
    setPriceError(null);
    const body: ItemIn = {
      category_id: initial?.category_id ?? categoryId ?? "",
      name, description: description || null, base_price_paise: paise, tax_class_id: taxClassId,
      station_id: stationId || null, veg_flag: veg, is_liquor: liquor,
      needs_approval: initial?.needs_approval ?? false, available: initial?.available ?? true,
      image_url: initial?.image_url ?? null, sort_order: initial?.sort_order ?? 0, sku: initial?.sku ?? null,
      modifier_group_ids: groups,
    };
    const ok = await action.run(() =>
      initial ? api(`${base}/items/${initial.id}`, { method: "PUT", body }) : api(`${base}/items`, { method: "POST", body }),
    );
    if (ok) { if (!initial) { setName(""); setPrice(""); setDescription(""); } onDone(); }
  }

  return (
    <form onSubmit={submit}>
      <div className="row">
        <Field label="Item name"><input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label={menu.prices_include_tax ? "Price (₹, with tax)" : "Price (₹, before tax)"} hint="Exactly as on your menu card.">
          <input required inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
        </Field>
      </div>
      <Field label="Description"><input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      <div className="row">
        <Field label="Tax class">
          <select required value={taxClassId} onChange={(e) => setTaxClassId(e.target.value)}>
            {menu.tax_classes.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </Field>
        <Field label="Station">
          <select value={stationId} onChange={(e) => setStationId(e.target.value)}>
            <option value="">None</option>
            {menu.stations.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </Field>
      </div>
      <label className="check"><input type="checkbox" checked={veg} onChange={(e) => setVeg(e.target.checked)} /> Vegetarian</label>
      <label className="check"><input type="checkbox" checked={liquor} onChange={(e) => setLiquor(e.target.checked)} /> Liquor</label>
      {menu.modifier_groups.length > 0 ? (
        <fieldset className="field">
          <legend className="field-label">Options guests can choose</legend>
          {menu.modifier_groups.map((g: ModifierGroup) => (
            <label key={g.id} className="check">
              <input type="checkbox" checked={groups.includes(g.id)} onChange={(e) => setGroups(e.target.checked ? [...groups, g.id] : groups.filter((x) => x !== g.id))} /> {g.name}
            </label>
          ))}
        </fieldset>
      ) : null}
      <ErrorBanner message={priceError ?? action.error} />
      <div className="inline">
        <button type="submit" disabled={action.busy || menu.tax_classes.length === 0}>{initial ? "Save item" : "Add item"}</button>
        {onCancel ? <button type="button" className="secondary" onClick={onCancel}>Cancel</button> : null}
        {menu.tax_classes.length === 0 ? <span className="muted">Add a tax class in Setup first.</span> : null}
      </div>
    </form>
  );
}

function ModifierGroups({ base, groups, reload }: { base: string; groups: ModifierGroup[]; reload: () => void }) {
  const [name, setName] = useState("");
  const [min, setMin] = useState("0");
  const [max, setMax] = useState("1");
  const [lines, setLines] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);
  const action = useAction();

  async function add(event: FormEvent) {
    event.preventDefault();
    const modifiers: { name: string; price_delta_paise: number }[] = [];
    for (const line of lines.split("\n").map((l) => l.trim()).filter(Boolean)) {
      const [label, extra] = line.split(",").map((p) => p.trim());
      const delta = extra ? parseRupees(extra) : 0;
      if (!label || delta === null) { setInputError(`Could not read "${line}". Use: Name, extra price (for example: Extra cheese, 30).`); return; }
      modifiers.push({ name: label, price_delta_paise: delta });
    }
    setInputError(null);
    if (await action.run(() => api(`${base}/modifier-groups`, { method: "POST", body: { name, min_select: Number(min), max_select: Number(max), modifiers } }))) {
      setName(""); setLines(""); reload();
    }
  }

  return (
    <Card title="Options (modifiers)">
      <ul>
        {groups.map((g) => (
          <li key={g.id} className="inline">
            <strong>{g.name}</strong> (choose {g.min_select}–{g.max_select}): {g.modifiers.map((m) => `${m.name}${m.price_delta_paise ? ` +${formatInr(m.price_delta_paise)}` : ""}`).join(", ")}
            <button type="button" className="danger" onClick={() => action.run(async () => { await api(`${base}/modifier-groups/${g.id}`, { method: "DELETE" }); reload(); })}>Remove</button>
          </li>
        ))}
      </ul>
      <form onSubmit={add}>
        <div className="row">
          <Field label="Group name"><input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Spice level" /></Field>
          <Field label="Choose at least"><input inputMode="numeric" value={min} onChange={(e) => setMin(e.target.value)} /></Field>
          <Field label="Choose at most"><input inputMode="numeric" value={max} onChange={(e) => setMax(e.target.value)} /></Field>
        </div>
        <Field label="Choices, one per line" hint="Add an extra price after a comma, for example: Extra cheese, 30">
          <textarea value={lines} onChange={(e) => setLines(e.target.value)} />
        </Field>
        <ErrorBanner message={inputError ?? action.error} />
        <button type="submit" disabled={action.busy}>Add options</button>
      </form>
    </Card>
  );
}
