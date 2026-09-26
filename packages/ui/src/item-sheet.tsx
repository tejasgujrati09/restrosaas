"use client";

import { useState } from "react";
import type { components } from "api-client";
import { formatInr } from "./format-inr";
import { Icon } from "./icons";
import { Sheet } from "./sheet";

type GuestItem = components["schemas"]["GuestItemOut"];

/** The item sheet: modifier groups with their min/max, quantity and a note. The server
 * re-checks everything; the live price here is display only (the cart shows the quote). */
export function ItemSheet({
  item,
  canOrder,
  showNote = true,
  onAdd,
  onClose,
}: {
  item: GuestItem | null;
  canOrder: boolean;
  /** Guests write kitchen instructions in the cart; a waiter adding items writes them here. */
  showNote?: boolean;
  onAdd: (entry: { qty: number; modifier_ids: string[]; note: string }) => void;
  onClose: () => void;
}) {
  return (
    <Sheet open={item !== null} onClose={onClose} title={item?.name ?? ""}>
      {item ? <ItemForm key={item.id} item={item} canOrder={canOrder} showNote={showNote} onAdd={onAdd} /> : null}
    </Sheet>
  );
}

function ItemForm({
  item,
  canOrder,
  showNote,
  onAdd,
}: {
  item: GuestItem;
  canOrder: boolean;
  showNote: boolean;
  onAdd: (entry: { qty: number; modifier_ids: string[]; note: string }) => void;
}) {
  const [qty, setQty] = useState(1);
  const [note, setNote] = useState("");
  // Nothing is preselected: a required choice must be an explicit tap, so an option that
  // costs extra is never added by default.
  const [chosen, setChosen] = useState<Record<string, string[]>>({});

  const groupsValid = item.modifier_groups.every((g) => {
    const n = chosen[g.id]?.length ?? 0;
    return n >= g.min_select && n <= g.max_select;
  });
  const picked = item.modifier_groups.flatMap((g) => g.modifiers.filter((m) => chosen[g.id]?.includes(m.id)));
  const unit = item.price_paise + picked.reduce((sum, m) => sum + m.price_delta_paise, 0);

  function toggle(groupId: string, modifierId: string, single: boolean, max: number) {
    setChosen((prev) => {
      const current = prev[groupId] ?? [];
      if (single) return { ...prev, [groupId]: [modifierId] };
      if (current.includes(modifierId)) return { ...prev, [groupId]: current.filter((id) => id !== modifierId) };
      if (current.length >= max) return prev;
      return { ...prev, [groupId]: [...current, modifierId] };
    });
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onAdd({ qty, modifier_ids: Object.values(chosen).flat(), note: note.trim() });
      }}
    >
      <p className="item-meta">
        <span className="item-price">{formatInr(unit)}</span>
        {item.price_rule ? <span className="muted">was {formatInr(item.base_price_paise)} · {item.price_rule.name}</span> : null}
        <span className="muted">{item.veg ? "Veg" : "Non-veg"}</span>
      </p>
      {item.description ? <p className="muted">{item.description}</p> : null}
      {item.modifier_groups.map((g) => {
        const single = g.max_select === 1;
        return (
          <fieldset key={g.id} className="group">
            <legend>
              {g.name}{" "}
              <span className="muted">
                {g.min_select > 0 ? "Required" : "Optional"}
                {single ? "" : `, up to ${g.max_select}`}
              </span>
            </legend>
            {g.modifiers.map((m) => (
              <label key={m.id} className="check">
                <input
                  type={single ? "radio" : "checkbox"}
                  name={g.id}
                  checked={chosen[g.id]?.includes(m.id) ?? false}
                  onChange={() => toggle(g.id, m.id, single, g.max_select)}
                />
                <span className="grow">{m.name}</span>
                {m.price_delta_paise ? <span>+{formatInr(m.price_delta_paise)}</span> : null}
              </label>
            ))}
          </fieldset>
        );
      })}
      {showNote ? (
      <details className="item-note">
        <summary>Add a note for the kitchen</summary>
        <label className="field">
          <span className="field-label">Note for the kitchen</span>
          <input value={note} maxLength={200} placeholder="e.g. Less spicy, no onion" onChange={(e) => setNote(e.target.value)} />
        </label>
      </details>
      ) : null}
      <div className="item-actions">
        <div className="qty-stepper" role="group" aria-label="Quantity">
          <button type="button" className="secondary icon-btn" aria-label="One less" disabled={qty <= 1} onClick={() => setQty(qty - 1)}>
            <Icon name="minus" />
          </button>
          <output aria-live="polite">{qty}</output>
          <button type="button" className="secondary icon-btn" aria-label="One more" disabled={qty >= 50} onClick={() => setQty(qty + 1)}>
            <Icon name="plus" />
          </button>
        </div>
        <button type="submit" className="btn-lg" disabled={!groupsValid || !item.available || !item.self_orderable}>
          {!item.available
            ? "Sold out"
            : !item.self_orderable
              ? "Ask your waiter"
              : !groupsValid
                ? "Choose your options"
                : `Add to cart · ${formatInr(unit * qty)}`}
        </button>
      </div>
      {!canOrder ? <p className="hint">Your waiter needs to confirm your table before you can place an order.</p> : null}
    </form>
  );
}
