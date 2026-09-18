"use client";

import Link from "next/link";
import { useHydrated, useSession } from "@/lib/session";

export default function Home() {
  const session = useSession();
  const hydrated = useHydrated();
  return (
    <main>
      <h1>Order at your table</h1>
      <p>Scan the QR code on your table to begin.</p>
      {hydrated && session && !session.ended ? (
        <p>
          <Link className="button" href="/menu">
            Back to table {session.table_label}
          </Link>
        </p>
      ) : null}
    </main>
  );
}
