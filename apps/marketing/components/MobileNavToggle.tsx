"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * The one interactive bit of the header: opens the nav on small screens, and closes both the
 * nav and the "Product" dropdown after a link is followed, on Escape, or on a click elsewhere.
 * (The header persists across client-side navigation, so an open <details> would otherwise stay
 * open on the next page.)
 */
export function MobileNavToggle({ id }: { id: string }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    document.getElementById(id)?.setAttribute("data-open", String(open));
  }, [id, open]);

  useEffect(() => {
    const nav = document.getElementById(id);
    if (!nav) return;
    const closeMenus = () => nav.querySelectorAll("details[open]").forEach((d) => d.removeAttribute("open"));
    const closeAll = () => {
      closeMenus();
      setOpen(false);
    };

    closeAll();

    const onClick = (e: MouseEvent) => {
      const target = e.target as Element | null;
      if (!target) return;
      if (target.closest("a") && nav.contains(target)) {
        closeAll();
        return;
      }
      if (!target.closest(".nav-product")) closeMenus();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeAll();
    };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [id, pathname]);

  return (
    <button
      type="button"
      className="nav-toggle secondary"
      aria-expanded={open}
      aria-controls={id}
      onClick={() => setOpen((v) => !v)}
    >
      <span className="visually-hidden">{open ? "Close menu" : "Open menu"}</span>
      <span aria-hidden="true">{open ? "Close" : "Menu"}</span>
    </button>
  );
}
