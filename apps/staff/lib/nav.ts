import type { IconName } from "@restosaas/ui";

export type NavItem = { href: string; label: string; icon: IconName; roles: string[] };
export type NavGroup = { label: string; items: NavItem[] };

/** Every destination, grouped by what the person is doing. Hiding a link is convenience only;
 *  the API refuses anything the role may not do. */
export const NAV: NavGroup[] = [
  {
    label: "Service",
    items: [
      { href: "floor", label: "Floor", icon: "grid", roles: ["owner", "manager", "waiter"] },
      { href: "requests", label: "Requests", icon: "bell", roles: ["owner", "manager", "waiter"] },
      { href: "kitchen", label: "Kitchen", icon: "flame", roles: ["owner", "manager", "kitchen", "bar"] },
    ],
  },
  {
    label: "Manage",
    items: [
      { href: "menu", label: "Menu", icon: "book", roles: ["owner", "manager", "waiter", "kitchen", "bar"] },
      { href: "price-rules", label: "Happy hours", icon: "tag", roles: ["owner", "manager"] },
      { href: "tables", label: "Tables & QR", icon: "qr", roles: ["owner", "manager"] },
      { href: "assignments", label: "Assign tables", icon: "users", roles: ["owner", "manager"] },
      { href: "staff", label: "Staff", icon: "user", roles: ["owner", "manager"] },
    ],
  },
  {
    label: "Settings",
    items: [{ href: "setup", label: "Setup", icon: "sliders", roles: ["owner"] }],
  },
];

/** Groups and items the given roles may see; empty groups are dropped. */
export function visibleNav(roles: string[]): NavGroup[] {
  return NAV.map((g) => ({ ...g, items: g.items.filter((i) => roles.some((r) => i.roles.includes(r))) })).filter(
    (g) => g.items.length > 0,
  );
}

/** Waiter, kitchen and bar work at night on a phone: they get the dark theme. Owners and
 *  managers, who also do admin at a desk, get the light one. */
export function usesDarkTheme(roles: string[]): boolean {
  return roles.length > 0 && roles.every((r) => r === "waiter" || r === "kitchen" || r === "bar");
}

/** The section of `/o/<outlet>/<section>/...` that a path is in. */
export function sectionOf(pathname: string): string {
  return pathname.split("/")[3] ?? "";
}

/** The phone tab bar shows at most three destinations, then "More" for the rest. */
export function splitForTabBar(items: NavItem[], max = 3): { primary: NavItem[]; more: NavItem[] } {
  return { primary: items.slice(0, max), more: items.slice(max) };
}
