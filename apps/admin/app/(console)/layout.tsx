"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Icon } from "@restosaas/ui";
import { getToken, clearSession, useToken } from "@/lib/session";

const NAV = [
  { href: "/restaurants", label: "Restaurants" },
  { href: "/audit", label: "Audit log" },
];

/** Everything behind sign-in: a slim top bar and a wide content column. */
export default function Console({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const token = useToken();

  // `token` is null during hydration even when signed in, so ask storage directly.
  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [token, router]);

  return (
    <>
      <header className="topbar">
        <p className="brand">Platform admin</p>
        <nav aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={pathname.startsWith(n.href) ? "page" : undefined}>
              {n.label}
            </Link>
          ))}
        </nav>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            clearSession();
            router.replace("/login");
          }}
        >
          <Icon name="logout" />
          Sign out
        </button>
      </header>
      <main>{children}</main>
    </>
  );
}
