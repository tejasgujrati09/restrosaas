"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { BottomBar } from "@/components/bottom-bar";
import { useHydrated, useSession } from "@/lib/session";

/** Every screen after the QR landing: needs a session, shows the bar. */
export default function Shell({ children }: { children: ReactNode }) {
  const session = useSession();
  const hydrated = useHydrated();
  const router = useRouter();

  useEffect(() => {
    if (hydrated && !session) router.replace("/");
  }, [hydrated, session, router]);

  if (!hydrated || !session) return <main aria-busy="true" />;
  if (session.ended) {
    return (
      <main>
        <h1>Your visit has ended</h1>
        <p>Thank you! To order again, start a new visit at this table.</p>
        <Link className="button" href={`/t/${encodeURIComponent(session.qr_token)}`}>
          Start a new order
        </Link>
      </main>
    );
  }
  return (
    <>
      <main>{children}</main>
      <BottomBar />
    </>
  );
}
