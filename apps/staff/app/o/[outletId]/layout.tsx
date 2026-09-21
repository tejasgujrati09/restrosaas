"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Icon, Notice, Sheet } from "@restosaas/ui";
import { useResource } from "@/components/hooks";
import { OfflineBanner } from "@/components/offline-banner";
import { live, socketUrl, useLive } from "@/lib/live";
import { sectionOf, splitForTabBar, usesDarkTheme, visibleNav, type NavItem } from "@/lib/nav";
import { clearSession, getToken, rolesAt } from "@/lib/session";
import { useToken } from "@/lib/use-token";
import type { OrdersList, RequestRow, Settings } from "@/lib/types";

export default function OutletLayout({ children }: { children: ReactNode }) {
  const { outletId } = useParams<{ outletId: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const token = useToken();
  const roles = useMemo(() => rolesAt(token, outletId), [token, outletId]);
  const settings = useResource<Settings>(token ? `/v1/outlets/${outletId}/settings` : null);
  const [moreOpen, setMoreOpen] = useState(false);

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
  // Orders waiting for a first look. Owners and managers only, and today only: the Orders screen
  // itself says when older orders are still open.
  const seesOrders = roles.some((r) => ["owner", "manager"].includes(r));
  const orders = useResource<OrdersList>(
    token && seesOrders ? `/v1/outlets/${outletId}/staff/orders?group=new` : null,
    30_000,
    true,
  );
  const fresh = orders.data?.counts.new ?? 0;

  // `token` is null during hydration even when signed in, so ask storage directly.
  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [token, router]);

  // Waiter, kitchen and bar work at night: dark. Set on <html> so the page background follows.
  const dark = usesDarkTheme(roles);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    return () => {
      delete document.documentElement.dataset.theme;
    };
  }, [dark]);

  const groups = visibleNav(roles);
  const section = sectionOf(pathname);
  const brand = settings.data ? settings.data.brand_name : "…";
  const suspended = settings.data?.suspended === true;
  const { primary, more } = splitForTabBar(groups.flatMap((g) => g.items));

  function signOut() {
    clearSession();
    router.replace("/login");
  }

  const link = (item: NavItem, className?: string) => (
    <Link
      key={item.href}
      href={`/o/${outletId}/${item.href}`}
      className={className}
      aria-current={section === item.href ? "page" : undefined}
      onClick={() => setMoreOpen(false)}
    >
      <Icon name={item.icon} />
      <span>{item.label}</span>
      {item.href === "requests" && open > 0 ? (
        <span className="badge count" aria-label={`${open} open`}>
          {open}
        </span>
      ) : null}
      {item.href === "orders" && fresh > 0 ? (
        <span className="badge count" aria-label={`${fresh} new`}>
          {fresh}
        </span>
      ) : null}
    </Link>
  );

  const status = (
    <span className={connected ? "conn" : "conn off"} title="Connection to the server">
      <span className="conn-dot" aria-hidden="true" />
      {connected ? "Live" : "Reconnecting…"}
    </span>
  );

  return (
    <div className="shell">
      <aside className="sidebar">
        <p className="brand">{brand}</p>
        <nav aria-label="Main">
          {groups.map((g) => (
            <div key={g.label} className="nav-group">
              <p className="nav-label">{g.label}</p>
              <ul>
                {g.items.map((i) => (
                  <li key={i.href}>{link(i, "nav-link")}</li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="side-foot">
          {status}
          <button type="button" className="secondary" onClick={signOut}>
            <Icon name="logout" />
            Sign out
          </button>
        </div>
      </aside>

      <div className="content-col">
        <header className="topbar">
          <p className="brand">{brand}</p>
          {status}
        </header>
        <OfflineBanner />
        <main>
          {suspended ? <Notice>This restaurant&apos;s account is suspended. You can look around, but changes are turned off. Please contact support.</Notice> : null}
          {/* A disabled fieldset turns off every button and field inside it; links still work. */}
          <fieldset className="readonly" disabled={suspended}>
            {children}
          </fieldset>
        </main>
      </div>

      <nav className="tabbar" aria-label="Main">
        {primary.map((i) => link(i, "tab"))}
        <button type="button" className="tab" onClick={() => setMoreOpen(true)}>
          <Icon name="more" />
          <span>More</span>
        </button>
      </nav>

      <Sheet open={moreOpen} onClose={() => setMoreOpen(false)} title="More">
        <ul className="more-list">
          {more.map((i) => (
            <li key={i.href}>{link(i, "nav-link")}</li>
          ))}
        </ul>
        <button type="button" className="secondary btn-lg wide" onClick={signOut}>
          <Icon name="logout" />
          Sign out
        </button>
      </Sheet>
    </div>
  );
}
