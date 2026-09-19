"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** A bottom sheet on the native <dialog> element: focus trap, Escape and backdrop for free. */
export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className="sheet"
      aria-labelledby="sheet-title"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      {open ? (
        <div className="sheet-body">
          <div className="sheet-head">
            <h2 id="sheet-title">{title}</h2>
            <button type="button" className="secondary" onClick={onClose} aria-label="Close">
              ✕
            </button>
          </div>
          {children}
        </div>
      ) : null}
    </dialog>
  );
}
