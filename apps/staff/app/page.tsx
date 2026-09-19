"use client";

import { useRouter } from "next/navigation";
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

  if (!choices) return <main><p>Loading…</p></main>;
  return (
    <main>
      <h1>Choose an outlet</h1>
      <ul>
        {choices.map((c) => (
          <li key={c.outletId}>
            <a href={`/o/${c.outletId}/${homeFor([c.role])}`}>{c.label}</a> <span className="badge">{c.role}</span>
          </li>
        ))}
      </ul>
    </main>
  );
}
