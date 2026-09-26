"use client";

import { useState, type FormEvent } from "react";

/** The kitchen instruction for one cart line. Collapsed it is one link; opened it is one field
 *  that saves on Enter, on "Save" or when you tap away, so the cart is not re-priced on every key. */
export function LineNote({ name, note, onSave }: { name: string; note: string; onSave: (note: string) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(note);

  function commit(event?: FormEvent) {
    event?.preventDefault();
    onSave(draft);
    setOpen(false);
  }

  if (!open) {
    return (
      <div className="line-note">
        {note ? <span className="muted">“{note}”</span> : null}
        <button
          type="button"
          className="tertiary"
          aria-label={`${note ? "Edit" : "Add"} kitchen note for ${name}`}
          onClick={() => { setDraft(note); setOpen(true); }}
        >
          {note ? "Edit note" : "Add a note for the kitchen"}
        </button>
      </div>
    );
  }
  return (
    <form className="line-note open" onSubmit={commit}>
      <label className="field">
        <span className="field-label">Note for the kitchen</span>
        <input
          autoFocus
          value={draft}
          maxLength={200}
          placeholder="e.g. Less spicy, no onion"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => commit()}
        />
      </label>
      <button type="submit" className="secondary">Save</button>
    </form>
  );
}
