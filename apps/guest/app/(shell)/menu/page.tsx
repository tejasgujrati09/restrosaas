"use client";

import Link from "next/link";
import { useState } from "react";
import { formatInr, Icon, ItemSheet, Notice } from "@restosaas/ui";

import { EmptyState, ErrorBanner, Skeleton } from "@/components/ui";
import { addToCart, useCart } from "@/lib/cart-store";
import { timeOf } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { GuestItem, GuestMenu, TabView } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

/** "Happy hour until 8:00 PM", from the first item the API says has a price rule on. */
function dealLine(menu: GuestMenu): string | null {
  for (const category of menu.categories) {
    for (const item of category.items) {
      if (item.price_rule) {
        const until = item.price_rule.ends_at ? ` until ${timeOf(item.price_rule.ends_at)}` : "";
        return `${item.price_rule.name}${until}`;
      }
    }
  }
  return null;
}

export default function MenuPage() {
  const session = useSession();
  const base = session ? `/v1/outlets/${session.outlet_id}` : null;
  const menu = useResource<GuestMenu>(base && `${base}/guest/menu`, 30_000, true);
  const tab = useResource<TabView>(session && base && `${base}/tabs/${session.tab_id}`, 5_000, true);
  const cart = useCart(session?.tab_id ?? null);
  const [vegOnly, setVegOnly] = useState(false);
  const [selected, setSelected] = useState<GuestItem | null>(null);

  if (!session) return null;
  if (!menu.data) return menu.error ? <ErrorBanner message={menu.error} /> : <Skeleton what="the menu" lines={6} />;

  const awaiting = tab.data?.awaiting_waiter ?? false;
  const count = cart.reduce((n, e) => n + e.qty, 0);
  const deal = dealLine(menu.data);
  const categories = menu.data.categories
    .map((c) => ({ ...c, items: c.items.filter((i) => !vegOnly || i.veg) }))
    .filter((c) => c.items.length > 0);

  return (
    <>
      <header className="g-head">
        <div>
          <h1>{menu.data.outlet_name}</h1>
          {deal ? <p className="deal-line">{deal}</p> : null}
        </div>
        <span className="table-pill">Table {session.table_label}</span>
      </header>
      {awaiting ? (
        <Notice>
          Waiting for your waiter to confirm this table. You can look at the menu, but ordering opens once they confirm.
        </Notice>
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
      {categories.length === 0 ? (
        <EmptyState
          title={vegOnly ? "No veg dishes right now" : "Nothing to show right now"}
          action={
            vegOnly ? (
              <button type="button" className="secondary" onClick={() => setVegOnly(false)}>
                Show everything
              </button>
            ) : undefined
          }
        >
          {vegOnly ? "Turn the filter off to see the full menu." : "The menu is being updated. Please ask your waiter."}
        </EmptyState>
      ) : null}
      {categories.map((c) => (
        <section key={c.id} id={`cat-${c.id}`} aria-labelledby={`h-${c.id}`}>
          <h2 id={`h-${c.id}`}>{c.name}</h2>
          {c.items.map((item) => (
            <button key={item.id} type="button" className="item" disabled={!item.available} onClick={() => setSelected(item)}>
              <span className={item.veg ? "dot" : "dot nonveg"} role="img" aria-label={item.veg ? "Veg" : "Non-veg"} />
              <span className="grow">
                <span className="name">{item.name}</span>
                {item.description ? <span className="desc">{item.description}</span> : null}
                {item.price_rule ? (
                  <span className="deal">
                    {item.price_rule.name}
                    {item.price_rule.ends_at ? ` until ${timeOf(item.price_rule.ends_at)}` : ""}
                  </span>
                ) : null}
                {!item.available ? (
                  <span className="desc">Sold out</span>
                ) : !item.self_orderable ? (
                  <span className="desc">Ask your waiter</span>
                ) : null}
              </span>
              <span className="price">
                {item.price_rule ? <span className="was">{formatInr(item.base_price_paise)}</span> : null}
                {formatInr(item.price_paise)}
              </span>
              {item.available && item.self_orderable ? (
                <span className="add" aria-hidden="true">
                  <Icon name="plus" />
                </span>
              ) : null}
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
        <Link className="button btn-lg cta" href="/cart">
          <span>View cart</span>
          <span>
            {count} {count === 1 ? "item" : "items"}
          </span>
        </Link>
      ) : null}
    </>
  );
}
