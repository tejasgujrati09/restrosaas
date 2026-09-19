"use client";

import { useRouter } from "next/navigation";
import { Badge, Skeleton } from "@restosaas/ui";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { homeFor } from "@/lib/floor";
import { claimsOf, getToken } from "@/lib/session";
import type { Settings } from "@/lib/types";

type Choice = { outletId: string; label: string; role: string };

export default function Home() {
  const router = useRouter();
  const [choices, setChoices] = useState<Choice[] | null>(null);

  useEffect(() => {
    const token = getToken();
    const claims = claimsOf(token);
    if (!token || claims.length === 0) {
      router.replace("/login");
      return;
    }
    Promise.all(
      claims.map(async (c) => {
        const s = await api<Settings>(`/v1/outlets/${c.outlet_id}/settings`);
        return { outletId: c.outlet_id, label: `${s.brand_name} — ${s.outlet_name}`, role: c.role };
      }),
    ).then((list) => {
      if (list.length === 1 && list[0]) router.replace(`/o/${list[0].outletId}/${homeFor([list[0].role])}`);
      else setChoices(list);
    });
  }, [router]);

  if (!choices) {
    return (
      <main className="auth">
        <Skeleton what="your outlets" lines={3} block />
      </main>
    );
  }
  return (
    <main className="auth">
      <h1>Choose an outlet</h1>
      <p className="muted">You work at more than one place. Pick where to start.</p>
      <ul className="list picker">
        {choices.map((c) => (
          <li key={c.outletId}>
            <a className="pick" href={`/o/${c.outletId}/${homeFor([c.role])}`}>
              <span>{c.label}</span>
              <Badge>{c.role}</Badge>
            </a>
          </li>
        ))}
      </ul>
    </main>
  );
}
