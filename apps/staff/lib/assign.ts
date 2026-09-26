import type { AutoStrategy, BoardTable, BoardWaiter } from "./types";

export const STRATEGIES: { value: AutoStrategy; label: string; hint: string }[] = [
  { value: "least_loaded", label: "Least busy waiter", hint: "The waiter with the fewest tables with guests right now." },
  { value: "nearest", label: "Nearest waiter", hint: "A waiter who already serves that zone, the one with the most tables in it. If nobody does, the least busy waiter." },
  { value: "rotation", label: "Waiters in turn", hint: "Each new table goes to the next waiter in a fixed order." },
];

/** Empty "+ Add table" slots to show after `tableCount` tables: the grid always keeps at least
 *  one, and starts with four so an empty venue shows a row to click rather than a blank page. */
export function placeholderCount(tableCount: number): number {
  return tableCount < 4 ? 4 - tableCount : 1;
}

/** The next free label in the style already used, e.g. T1, T2 give T3; B7 gives B8. */
export function nextLabel(labels: string[], fallbackPrefix = "T"): string {
  let prefix = fallbackPrefix;
  let max = 0;
  for (const label of labels) {
    const m = /^(.*?)(\d+)$/.exec(label);
    if (!m) continue;
    const n = Number(m[2]);
    if (n >= max) { max = n; prefix = m[1] ?? fallbackPrefix; }
  }
  const taken = new Set(labels.map((l) => l.toLowerCase()));
  let n = max + 1;
  while (taken.has(`${prefix}${n}`.toLowerCase())) n += 1;
  return `${prefix}${n}`;
}

const nameOf = (w: { name: string | null; phone: string }) => w.name ?? w.phone;

/** What assigning `waiter` to the selected tables would change, one line per table whose
 *  waiter is different today, so a change is never a surprise. Empty when nothing changes. */
export function changeNotes(tables: BoardTable[], selected: Set<string>, waiter: BoardWaiter | null): string[] {
  const notes: string[] = [];
  for (const t of tables) {
    if (!selected.has(t.table_id)) continue;
    const current = t.waiters.map(nameOf);
    if (waiter === null) {
      if (current.length) notes.push(`${t.label}: ${current.join(", ")} will be removed`);
    } else if (current.length === 0) {
      notes.push(`${t.label}: no waiter yet`);
    } else if (!(t.waiters.length === 1 && t.waiters[0]?.user_id === waiter.user_id)) {
      notes.push(`${t.label}: ${current.join(", ")} will be replaced by ${nameOf(waiter)}`);
    }
  }
  return notes;
}

export function waiterName(w: BoardWaiter): string {
  return nameOf(w);
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
