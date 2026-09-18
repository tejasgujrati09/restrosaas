"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { CallSheet } from "./call-sheet";

/** Menu · Tab · Call waiter, on every screen. */
export function BottomBar() {
  const path = usePathname();
  const [calling, setCalling] = useState(false);
  return (
    <>
      <nav className="bar" aria-label="Main">
        <Link href="/menu" aria-current={path === "/menu" || path === "/cart" ? "page" : undefined}>
          Menu
        </Link>
        <Link href="/tab" aria-current={path === "/tab" ? "page" : undefined}>
          My tab
        </Link>
        <button type="button" className="secondary" onClick={() => setCalling(true)}>
          Call waiter
        </button>
      </nav>
      <CallSheet open={calling} onClose={() => setCalling(false)} />
    </>
  );
}
