"use client";

import { useState, type FormEvent } from "react";
import { Field } from "@/components/ui";
import { useAction } from "@/components/hooks";
import { api } from "@/lib/api";

/** One table, added inline where its "+ Add table" slot was. Every field starts empty and shows
 *  a hint only, so nothing has to be deleted before typing; the form closes on success and the
 *  next slot opens blank again. The zone field appears only when the slot has no zone of its own. */
export function AddTable({
  base,
  zone,
  suggestion,
  onDone,
  onCancel,
}: {
  base: string;
  zone?: string;
  suggestion: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [zoneInput, setZoneInput] = useState("");
  const [label, setLabel] = useState("");
  const [seats, setSeats] = useState("");
  const action = useAction();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(() =>
      api(`${base}/tables`, {
        method: "POST",
        body: { label: label.trim(), zone: zone ?? (zoneInput.trim() || "floor"), seats: Number(seats) || 2 },
      }),
    );
    if (ok) onDone();
  }

  return (
    <form className="tile placeholder adding" onSubmit={submit} aria-label={zone ? `Add a table to ${zone}` : "Add a table"}>
      {zone === undefined ? (
        <Field label="Zone"><input value={zoneInput} maxLength={50} placeholder="e.g. Floor, Bar, Terrace" onChange={(e) => setZoneInput(e.target.value)} /></Field>
      ) : null}
      <Field label="Table name"><input required autoFocus maxLength={20} value={label} placeholder={`e.g. ${suggestion}`} onChange={(e) => setLabel(e.target.value)} /></Field>
      <Field label="Seats" size="short"><input inputMode="numeric" value={seats} placeholder="2" onChange={(e) => setSeats(e.target.value)} /></Field>
      <span className="inline">
        <button type="submit" disabled={action.busy}>Add</button>
        <button type="button" className="tertiary" onClick={onCancel}>Cancel</button>
      </span>
    </form>
  );
}
