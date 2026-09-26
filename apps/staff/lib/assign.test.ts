import { describe, expect, it } from "vitest";
import { changeNotes, nextLabel, placeholderCount, plural } from "./assign";
import type { BoardTable, BoardWaiter } from "./types";

const waiter = (id: string, name: string): BoardWaiter => ({ user_id: id, name, phone: "+91", tables: 0, active_tables: 0 });
const table = (id: string, label: string, waiters: BoardWaiter[] = []): BoardTable => ({
  table_id: id, label, zone: "floor", seats: 2, state: "empty", waiters: waiters.map((w) => ({ user_id: w.user_id, name: w.name, phone: w.phone })),
  auto_assigned: false, needs_waiter: false, waiting_orders: [],
});

describe("placeholders", () => {
  it("starts with four and keeps one once there are enough tables", () => {
    expect([0, 1, 2, 3, 4, 9].map(placeholderCount)).toEqual([4, 3, 2, 1, 1, 1]);
  });
});

describe("nextLabel", () => {
  it("continues the numbering in the style already used", () => {
    expect(nextLabel([])).toBe("T1");
    expect(nextLabel(["T1", "T2"])).toBe("T3");
    expect(nextLabel(["B7"])).toBe("B8");
    expect(nextLabel(["Patio", "T4"])).toBe("T5");
    expect(nextLabel(["T1", "T3"])).toBe("T4");
  });
});

describe("changeNotes", () => {
  const rahul = waiter("r", "Rahul");
  const amit = waiter("a", "Amit");
  const tables = [table("1", "T1"), table("2", "T2", [amit]), table("3", "T3", [rahul]), table("4", "T4", [amit])];

  it("says what changes for each selected table, and skips ones already right", () => {
    const notes = changeNotes(tables, new Set(["1", "2", "3"]), rahul);
    expect(notes).toEqual(["T1: no waiter yet", "T2: Amit will be replaced by Rahul"]);
  });

  it("describes clearing a waiter and ignores unselected tables", () => {
    expect(changeNotes(tables, new Set(["2", "1"]), null)).toEqual(["T2: Amit will be removed"]);
    expect(changeNotes(tables, new Set(), rahul)).toEqual([]);
  });
});

describe("plural", () => {
  it("counts", () => {
    expect(plural(1, "table")).toBe("1 table");
    expect(plural(3, "table")).toBe("3 tables");
  });
});
