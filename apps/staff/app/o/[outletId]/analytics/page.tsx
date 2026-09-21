"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useRef, useState } from "react";
import { EmptyState, Field, PageHeader, Skeleton } from "@restosaas/ui";
import { DrillPanel } from "@/components/analytics-drill";
import {
  KitchenPanel,
  MenuPanel,
  OverviewPanel,
  StaffPanel,
  TablesPanel,
  type Drill,
} from "@/components/analytics-panels";
import { PRESETS, rangeParams, type Preset, type RangeChoice } from "@/lib/analytics";
import { rolesAt } from "@/lib/session";
import { useToken } from "@/lib/use-token";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "kitchen", label: "Kitchen" },
  { key: "staff", label: "Staff" },
  { key: "menu", label: "Menu" },
  { key: "tables", label: "Tables" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

function useView(): { tab: TabKey; range: RangeChoice; update: (tab: TabKey, range: RangeChoice) => void } {
  const search = useSearchParams();
  const router = useRouter();
  const tab = TABS.find((t) => t.key === search.get("tab"))?.key ?? "overview";
  const preset = (PRESETS.find((x) => x.value === search.get("range"))?.value ?? "last_7_days") as Preset;
  const range = useMemo<RangeChoice>(
    () => ({ preset, from: search.get("from") ?? "", to: search.get("to") ?? "" }),
    [preset, search],
  );
  // The address holds the tab and range, so a refresh or a shared link shows the same view.
  const update = (nextTab: TabKey, next: RangeChoice) => {
    const p = new URLSearchParams({ tab: nextTab, range: next.preset });
    if (next.preset === "custom") {
      p.set("from", next.from);
      p.set("to", next.to);
    }
    router.replace(`?${p}`, { scroll: false });
  };
  return { tab, range, update };
}

export default function AnalyticsPage() {
  return (
    <Suspense fallback={<Skeleton what="analytics" lines={4} />}>
      <Analytics />
    </Suspense>
  );
}

function Analytics() {
  const { outletId } = useParams<{ outletId: string }>();
  const token = useToken();
  const roles = useMemo(() => rolesAt(token, outletId), [token, outletId]);
  const { tab, range, update } = useView();
  const [drill, setDrill] = useState<Drill | null>(null);
  const drillRef = useRef<HTMLDivElement>(null);

  const params = rangeParams(range);
  const query = params?.toString() ?? null;
  const allowed = roles.some((r) => r === "owner" || r === "manager");
  const today = new Date().toLocaleDateString("en-CA");

  function open(next: Drill) {
    setDrill(next);
    window.setTimeout(() => drillRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }

  if (token && !allowed) {
    return (
      <div className="narrow">
        <PageHeader title="Analytics" />
        <EmptyState title="Analytics is for owners and managers">Ask the owner if you need to see these figures.</EmptyState>
      </div>
    );
  }

  const Panel = { overview: OverviewPanel, kitchen: KitchenPanel, staff: StaffPanel, menu: MenuPanel, tables: TablesPanel }[tab];

  return (
    <div>
      <PageHeader
        title="Analytics"
        subtitle="How the restaurant is doing, from the orders, kitchen tickets and serving your team records."
        actions={
          <div className="range-controls">
            <Field label="Date range">
              <select
                value={range.preset}
                onChange={(e) => {
                  setDrill(null);
                  update(tab, { ...range, preset: e.target.value as Preset });
                }}
              >
                {PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </Field>
            {range.preset === "custom" ? (
              <>
                <Field label="From">
                  <input type="date" max={today} value={range.from} onChange={(e) => update(tab, { ...range, from: e.target.value })} />
                </Field>
                <Field label="To">
                  <input type="date" max={today} value={range.to} onChange={(e) => update(tab, { ...range, to: e.target.value })} />
                </Field>
              </>
            ) : null}
          </div>
        }
      />
      <div className="tabs" role="tablist" aria-label="Analytics sections">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            id={`tab-${t.key}`}
            aria-selected={tab === t.key}
            aria-controls="an-panel"
            onClick={() => {
              setDrill(null);
              update(t.key, range);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div id="an-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="an-panel">
        {query === null ? (
          <EmptyState title="Choose both dates">Pick a start and an end date for a custom range.</EmptyState>
        ) : (
          <>
            {/* Keyed by range and section so switching shows a fresh skeleton, never last range's numbers. */}
            <Panel key={`${tab}:${query}`} outletId={outletId} query={query} onDrill={open} />
            {drill ? (
              <div ref={drillRef}>
                <DrillPanel key={`${query}|${JSON.stringify(drill.params)}`} outletId={outletId} query={query} drill={drill} onClose={() => setDrill(null)} />
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
