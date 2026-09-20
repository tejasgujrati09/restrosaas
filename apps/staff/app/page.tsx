"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Badge, EmptyState, Icon, Notice, PageHeader, Skeleton } from "@restosaas/ui";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { homeFor } from "@/lib/floor";
import { groupClaims, initialOf, rolesPhrase, type OutletChoice } from "@/lib/outlets";
import { clearSession, claimsOf, getToken } from "@/lib/session";
import { STATES } from "@/lib/states";
import type { Settings } from "@/lib/types";

type Card = OutletChoice & { brand: string; outlet: string; state: string | null; ready: boolean; suspended: boolean };

export default function Home() {
  const router = useRouter();
  const [cards, setCards] = useState<Card[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(0);

  const load = useCallback(() => {
    const token = getToken();
    const choices = groupClaims(claimsOf(token));
    if (!token || choices.length === 0) {
      router.replace("/login");
      return;
    }
    // One restaurant failing to load must not hide the others.
    Promise.allSettled(
      choices.map(async (c) => {
        const s = await api<Settings>(`/v1/outlets/${c.outletId}/settings`);
        const state = STATES.find(([code]) => code === s.state_code)?.[1] ?? null;
        return { ...c, brand: s.brand_name, outlet: s.outlet_name, state, ready: s.ready_to_go_live, suspended: s.suspended };
      }),
    ).then((results) => {
      const list = results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
      if (list.length === 0) {
        setError("We could not load your restaurants. Check your connection and try again.");
        return;
      }
      // One place to work: no need to choose.
      if (list.length === 1 && choices.length === 1 && list[0]) router.replace(`/o/${list[0].outletId}/${homeFor(list[0].roles)}`);
      else {
        setMissing(choices.length - list.length);
        setCards(list);
      }
    });
  }, [router]);

  useEffect(load, [load]);

  function signOut() {
    clearSession();
    router.replace("/login");
  }

  return (
    <main className="picker-page">
      <PageHeader
        title="Choose a restaurant"
        subtitle="You work at more than one place. Pick where to start."
        actions={
          <button type="button" className="secondary" onClick={signOut}>
            <Icon name="logout" />
            Sign out
          </button>
        }
      />
      {error ? (
        <>
          <ErrorBanner message={error} />
          <button
            type="button"
            onClick={() => {
              setError(null);
              setMissing(0);
              load();
            }}
          >
            Try again
          </button>
        </>
      ) : !cards ? (
        <div className="outlet-grid" aria-busy="true">
          <Skeleton what="your restaurants" lines={3} block />
        </div>
      ) : cards.length === 0 ? (
        <EmptyState title="No restaurants yet">Ask the owner to invite you, or create your own restaurant.</EmptyState>
      ) : (
        <>
        {missing > 0 ? <Notice>{missing === 1 ? "One restaurant" : `${missing} restaurants`} could not be loaded. Reload the page to try again.</Notice> : null}
        <ul className="outlet-grid">
          {cards.map((c) => (
            <li key={c.outletId}>
              <a className="outlet-card" href={`/o/${c.outletId}/${homeFor(c.roles)}`}>
                <span className="avatar" aria-hidden="true">
                  {initialOf(c.brand)}
                </span>
                <span className="names">
                  <strong>{c.brand}</strong>
                  <span>
                    {c.outlet}
                    {c.state ? ` · ${c.state}` : ""}
                  </span>
                </span>
                <span className="meta">
                  <Badge>{rolesPhrase(c.roles)}</Badge>
                  {c.suspended ? (
                    <Badge tone="danger">Suspended</Badge>
                  ) : c.ready ? (
                    <Badge tone="ok">Open for guests</Badge>
                  ) : (
                    <Badge tone="warn">Setup not finished</Badge>
                  )}
                </span>
                <span className="go" aria-hidden="true">
                  <Icon name="chevron" />
                </span>
              </a>
            </li>
          ))}
        </ul>
        </>
      )}
    </main>
  );
}
