"use client";

import Link from "next/link";
import { useState } from "react";
import { formatInr } from "@restosaas/ui";
import { ItemSheet } from "@/components/item-sheet";
import { ErrorBanner, Loading } from "@/components/ui";
import { addToCart, useCart } from "@/lib/cart-store";
import { timeOf } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { GuestItem, GuestMenu, TabView } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

export default function MenuPage() {
  const session = useSession();
  const base = session ? `/v1/outlets/${session.outlet_id}` : null;
  const menu = useResource<GuestMenu>(base && `${base}/guest/menu`, 30_000);
  const tab = useResource<TabView>(session && base && `${base}/tabs/${session.tab_id}`, 5_000);
  const cart = useCart(session?.tab_id ?? null);
  const [vegOnly, setVegOnly] = useState(false);
  const [selected, setSelected] = useState<GuestItem | null>(null);

  if (!session) return null;
  if (!menu.data) return menu.error ? <ErrorBanner message={menu.error} /> : <Loading what="the menu" />;

  const awaiting = tab.data?.awaiting_waiter ?? false;
  const count = cart.reduce((n, e) => n + e.qty, 0);
  const categories = menu.data.categories
    .map((c) => ({ ...c, items: c.items.filter((i) => !vegOnly || i.veg) }))
    .filter((c) => c.items.length > 0);

  return (
    <>
      <h1>{menu.data.outlet_name}</h1>
      <p className="muted">Table {session.table_label}</p>
      {awaiting ? (
        <p className="banner" role="status">
          Waiting for your waiter to confirm this table. You can look at the menu, but ordering opens once they confirm.
        </p>
      ) : null}
      <ErrorBanner message={menu.error} />
      <div className="chips" role="group" aria-label="Filter and jump to a section">
        <button type="button" aria-pressed={vegOnly} onClick={() => setVegOnly(!vegOnly)}>
          Veg only
        </button>
        {categories.map((c) => (
          <a key={c.id} href={`#cat-${c.id}`}>
            {c.name}
          </a>
        ))}
      </div>
      {categories.length === 0 ? <p>Nothing to show right now.</p> : null}
      {categories.map((c) => (
        <section key={c.id} id={`cat-${c.id}`} aria-labelledby={`h-${c.id}`}>
          <h2 id={`h-${c.id}`}>{c.name}</h2>
          {c.items.map((item) => (
            <button key={item.id} type="button" className="item" disabled={!item.available} onClick={() => setSelected(item)}>
              <span className={item.veg ? "dot" : "dot nonveg"} role="img" aria-label={item.veg ? "Veg" : "Non-veg"} />
              <span className="grow">
                <span className="name">{item.name}</span>
                {item.price_rule ? (
                  <span className="deal" style={{ display: "block" }}>
                    {item.price_rule.name}
                    {item.price_rule.ends_at ? ` until ${timeOf(item.price_rule.ends_at)}` : ""}
                  </span>
                ) : null}
                {!item.available ? (
                  <span className="muted" style={{ display: "block" }}>
                    Sold out
                  </span>
                ) : !item.self_orderable ? (
                  <span className="muted" style={{ display: "block" }}>
                    Ask your waiter
                  </span>
                ) : null}
              </span>
              <span>
                {item.price_rule ? <span className="was">{formatInr(item.base_price_paise)}</span> : null}
                {formatInr(item.price_paise)}
              </span>
            </button>
          ))}
        </section>
      ))}
      <ItemSheet
        item={selected}
        canOrder={!awaiting}
        onClose={() => setSelected(null)}
        onAdd={(entry) => {
          if (selected) addToCart(session.tab_id, { menu_item_id: selected.id, name: selected.name, ...entry });
          setSelected(null);
        }}
      />
      {count > 0 ? (
        <Link className="button float" href="/cart">
          View cart · {count}
        </Link>
      ) : null}
    </>
  );
}
