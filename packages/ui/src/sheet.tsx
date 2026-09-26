"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Icon } from "./icons";

/** A bottom sheet on the native <dialog> element: focus trap, Escape and backdrop for free. */
export function Sheet({
  open,
  onClose,
  title,
  variant = "sheet",
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  /** "drawer" docks to the right edge on a wide screen so the page beside it stays visible (a long
   *  record such as an order); on a phone it is the same bottom sheet. */
  variant?: "sheet" | "drawer";
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
      className={variant === "drawer" ? "sheet drawer" : "sheet"}
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
            <button type="button" className="secondary icon-btn" onClick={onClose} aria-label="Close">
              <Icon name="close" />
            </button>
          </div>
          <div className="sheet-content">{children}</div>
        </div>
      ) : null}
    </dialog>
  );
}
