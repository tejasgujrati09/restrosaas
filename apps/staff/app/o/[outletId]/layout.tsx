"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, type ReactNode } from "react";
import { useResource } from "@/components/hooks";
import { clearSession, getToken, rolesAt } from "@/lib/session";
import { useToken } from "@/lib/use-token";
import type { Settings } from "@/lib/types";

const LINKS: { href: string; label: string; roles: string[] }[] = [
  { href: "setup", label: "Setup", roles: ["owner"] },
  { href: "menu", label: "Menu", roles: ["owner", "manager", "waiter", "kitchen", "bar"] },
  { href: "price-rules", label: "Happy hours", roles: ["owner", "manager"] },
  { href: "tables", label: "Tables & QR", roles: ["owner", "manager"] },
  { href: "staff", label: "Staff", roles: ["owner", "manager"] },
];

export default function OutletLayout({ children }: { children: ReactNode }) {
  const { outletId } = useParams<{ outletId: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const token = useToken();
  const roles = useMemo(() => rolesAt(token, outletId), [token, outletId]);
  const settings = useResource<Settings>(token ? `/v1/outlets/${outletId}/settings` : null);

  // `token` is null during hydration even when signed in, so ask storage directly.
  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [token, router]);

  // Hiding a link is convenience only; the API refuses anything the role may not do.
  const visible = LINKS.filter((l) => roles.some((r) => l.roles.includes(r)));

  return (
    <>
      <nav className="top" aria-label="Main">
        <ul>
          <li><strong>{settings.data ? settings.data.brand_name : "…"}</strong></li>
          {visible.map((l) => (
            <li key={l.href}>
              <Link href={`/o/${outletId}/${l.href}`} aria-current={pathname.endsWith(`/${l.href}`) ? "page" : undefined}>{l.label}</Link>
            </li>
          ))}
          <li className="spacer" />
          <li>
            <button type="button" className="secondary" onClick={() => { clearSession(); router.replace("/login"); }}>Sign out</button>
          </li>
        </ul>
      </nav>
      <main>{children}</main>
    </>
  );
}
