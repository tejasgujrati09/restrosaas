"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, type ReactNode } from "react";
import { useResource } from "@/components/hooks";
import { live, socketUrl, useLive } from "@/lib/live";
import { clearSession, getToken, rolesAt } from "@/lib/session";
import { useToken } from "@/lib/use-token";
import type { RequestRow, Settings } from "@/lib/types";

const LINKS: { href: string; label: string; roles: string[] }[] = [
  { href: "floor", label: "Floor", roles: ["owner", "manager", "waiter"] },
  { href: "requests", label: "Requests", roles: ["owner", "manager", "waiter"] },
  { href: "kitchen", label: "Kitchen", roles: ["owner", "manager", "kitchen", "bar"] },
  { href: "setup", label: "Setup", roles: ["owner"] },
  { href: "menu", label: "Menu", roles: ["owner", "manager", "waiter", "kitchen", "bar"] },
  { href: "price-rules", label: "Happy hours", roles: ["owner", "manager"] },
  { href: "tables", label: "Tables & QR", roles: ["owner", "manager"] },
  { href: "staff", label: "Staff", roles: ["owner", "manager"] },
  { href: "assignments", label: "Assign tables", roles: ["owner", "manager"] },
];

export default function OutletLayout({ children }: { children: ReactNode }) {
  const { outletId } = useParams<{ outletId: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const token = useToken();
  const roles = useMemo(() => rolesAt(token, outletId), [token, outletId]);
  const settings = useResource<Settings>(token ? `/v1/outlets/${outletId}/settings` : null);

  // One live socket for everything on screen; screens refetch when it pushes.
  useEffect(() => {
    if (!token) return;
    live.start({ token, url: socketUrl(outletId) });
    return () => live.stop();
  }, [token, outletId]);
  const { connected } = useLive();
  const seesFloor = roles.some((r) => ["owner", "manager", "waiter"].includes(r));
  const requests = useResource<RequestRow[]>(token && seesFloor ? `/v1/outlets/${outletId}/staff/service-requests` : null, 30_000, true);
  const open = requests.data?.length ?? 0;

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
              <Link href={`/o/${outletId}/${l.href}`} aria-current={pathname.includes(`/${l.href}`) ? "page" : undefined}>
                {l.label}
                {l.href === "requests" && open > 0 ? <span className="badge count" aria-label={`${open} open`}>{open}</span> : null}
              </Link>
            </li>
          ))}
          <li className="spacer" />
          <li className={connected ? "muted" : "warn"} role="status">{connected ? "Live" : "Reconnecting…"}</li>
          <li>
            <button type="button" className="secondary" onClick={() => { clearSession(); router.replace("/login"); }}>Sign out</button>
          </li>
        </ul>
      </nav>
      <main>{children}</main>
    </>
  );
}
