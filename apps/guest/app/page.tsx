"use client";

import Link from "next/link";
import { Icon } from "@restosaas/ui";
import { useHydrated, useSession } from "@/lib/session";

export default function Home() {
  const session = useSession();
  const hydrated = useHydrated();
  return (
    <main className="center">
      <span className="mark-lg" aria-hidden="true">
        <Icon name="qr" size={32} />
      </span>
      <h1>Order at your table</h1>
      <p className="muted">Scan the QR code on your table to begin.</p>
      {hydrated && session && !session.ended ? (
        <Link className="button btn-lg" href="/menu">
          Back to table {session.table_label}
        </Link>
      ) : null}
    </main>
  );
}
