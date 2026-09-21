"use client";

import type { ReactNode } from "react";
import { Badge } from "@restosaas/ui";
import { barShares, basisText, changeText, formatKpiValue, heatShare, hourLabel, WEEKDAYS } from "@/lib/analytics";
import type { Kpi } from "@/lib/types";

/** One number, what it is based on, how it compares, and how it is calculated. */
export function KpiCard({ title, kpi, note }: { title: string; kpi: Kpi; note?: string }) {
  const change = changeText(kpi);
  return (
    <article className="kpi">
      <h3>{title}</h3>
      <p className="kpi-value">{formatKpiValue(kpi, kpi.value)}</p>
      {kpi.value !== null ? <p className="kpi-basis">{basisText(kpi)}</p> : <p className="kpi-basis">Nothing to measure in this range</p>}
      {change ? <p className="kpi-change">{change}</p> : null}
      {change && kpi.previous !== null ? <p className="kpi-basis">Previous: {formatKpiValue(kpi, kpi.previous)}</p> : null}
      {note ? <p className="kpi-basis">{note}</p> : null}
      <details className="kpi-how">
        <summary>How is this calculated?</summary>
        <p>{kpi.definition}</p>
        {kpi.excluded ? <p>Left out: {kpi.excluded}</p> : null}
      </details>
    </article>
  );
}

export type BarItem = { key: string; label: string; value: number | null; text: string };

/** A bar chart made of HTML, so labels keep their real size on a phone. Each bar has its
 *  number in a tooltip and the same numbers are in the table below for screen readers. */
export function Bars({
  items,
  name,
  unitLabel,
  labelEvery = 1,
}: {
  items: BarItem[];
  name: string;
  unitLabel: string;
  labelEvery?: number;
}) {
  const shares = barShares(items.map((i) => i.value));
  return (
    <figure className="chart">
      <div className="bars" role="img" aria-label={`${name}. ${items.filter((i) => i.value).length} of ${items.length} have data.`}>
        {items.map((item, i) => (
          <div key={item.key} className="bar-col" title={`${item.label}: ${item.text}`}>
            <div className="bar-track">
              <div className={item.value ? "bar" : "bar none"} style={{ height: `${shares[i]}%` }} />
            </div>
            <span className="bar-label">{i % labelEvery === 0 ? item.label : " "}</span>
          </div>
        ))}
      </div>
      <details className="chart-table">
        <summary>See the numbers</summary>
        <table className="stacked">
          <thead>
            <tr>
              <th>{name}</th>
              <th>{unitLabel}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.key}>
                <td data-label={name}>{item.label}</td>
                <td data-label={unitLabel}>{item.text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

/** Rounds by weekday and hour. Darker means more; the number is in every cell's tooltip. */
export function Heatmap({ grid }: { grid: number[][] }) {
  const top = Math.max(0, ...grid.flat());
  const hours = Array.from({ length: 24 }, (_, h) => h);
  return (
    <div className="heat-wrap">
      <table className="heat" aria-label="Rounds by weekday and hour">
        <thead>
          <tr>
            <th scope="col">
              <span className="visually-hidden">Weekday</span>
            </th>
            {hours.map((h) => (
              <th key={h} scope="col" className="heat-h">
                {h % 3 === 0 ? hourLabel(h).replace(" ", "") : <span className="visually-hidden">{hourLabel(h)}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grid.map((row, d) => (
            <tr key={WEEKDAYS[d]}>
              <th scope="row">{WEEKDAYS[d]}</th>
              {row.map((count, h) => (
                <td
                  key={h}
                  className="heat-cell"
                  title={`${WEEKDAYS[d]} ${hourLabel(h)}: ${count} rounds`}
                  style={{ ["--heat" as string]: `${heatShare(count, top)}%` }}
                >
                  <span className="visually-hidden">{count}</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SectionHead({ title, hint, actions }: { title: string; hint?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="section-head">
      <div>
        <h2>{title}</h2>
        {hint ? <p className="hint">{hint}</p> : null}
      </div>
      {actions ? <div className="actions">{actions}</div> : null}
    </div>
  );
}

export function LowSample() {
  return <Badge tone="warn">Few tickets</Badge>;
}
