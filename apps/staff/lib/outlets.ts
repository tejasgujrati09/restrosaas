import type { Claim } from "./session";

export type OutletChoice = { outletId: string; restaurantId: string; roles: string[] };

const ROLE_ORDER = ["owner", "manager", "waiter", "kitchen", "bar"];

/** One entry per outlet, however many roles the person holds there; highest role first. */
export function groupClaims(claims: Claim[]): OutletChoice[] {
  const byOutlet = new Map<string, OutletChoice>();
  for (const c of claims) {
    const found = byOutlet.get(c.outlet_id);
    if (found) {
      if (!found.roles.includes(c.role)) found.roles.push(c.role);
    } else {
      byOutlet.set(c.outlet_id, { outletId: c.outlet_id, restaurantId: c.restaurant_id, roles: [c.role] });
    }
  }
  const rank = (r: string) => (ROLE_ORDER.includes(r) ? ROLE_ORDER.indexOf(r) : ROLE_ORDER.length);
  return [...byOutlet.values()].map((o) => ({ ...o, roles: [...o.roles].sort((a, b) => rank(a) - rank(b)) }));
}

/** The letter shown on a restaurant's card when it has no logo. */
export function initialOf(name: string): string {
  const first = [...name.trim()][0];
  return first ? first.toUpperCase() : "?";
}

/** "Owner", "Manager and waiter": the roles as a short phrase for a card. */
export function rolesPhrase(roles: string[]): string {
  const words = roles.map((r, i) => (i === 0 ? r.charAt(0).toUpperCase() + r.slice(1) : r));
  return words.length <= 1 ? (words[0] ?? "") : `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
}
