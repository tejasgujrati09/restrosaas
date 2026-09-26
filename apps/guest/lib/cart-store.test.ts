import { beforeEach, describe, expect, it, vi } from "vitest";
import { addToCart, readCart, setNote, setQty, writeCart } from "./cart-store";
import { stubBrowser } from "./test-env";

let n = 0;
beforeEach(() => {
  vi.unstubAllGlobals();
  stubBrowser();
  n = 0;
  vi.stubGlobal("crypto", { randomUUID: () => `key-${++n}` });
});

const entry = { menu_item_id: "a", name: "Tikka", qty: 1, modifier_ids: ["m1", "m2"], note: "" };

describe("cart store", () => {
  it("is empty and stable until something is added", () => {
    expect(readCart("tab")).toEqual([]);
    expect(readCart("tab")).toBe(readCart("tab"));
  });

  it("keeps carts separate per tab", () => {
    addToCart("tab1", entry);
    expect(readCart("tab1")).toHaveLength(1);
    expect(readCart("tab2")).toHaveLength(0);
  });

  it("merges the same item with the same choices, whatever their order", () => {
    addToCart("tab", entry);
    addToCart("tab", { ...entry, modifier_ids: ["m2", "m1"], qty: 2 });
    expect(readCart("tab")).toEqual([{ ...entry, key: "key-1", qty: 3 }]);
  });

  it("keeps different choices or notes as separate lines", () => {
    addToCart("tab", entry);
    addToCart("tab", { ...entry, note: "less oil" });
    addToCart("tab", { ...entry, modifier_ids: ["m1"] });
    expect(readCart("tab")).toHaveLength(3);
  });

  it("caps a line at 50", () => {
    addToCart("tab", { ...entry, qty: 49 });
    addToCart("tab", { ...entry, qty: 10 });
    expect(readCart("tab")[0]?.qty).toBe(50);
    setQty("tab", "key-1", 99);
    expect(readCart("tab")[0]?.qty).toBe(50);
  });

  it("sets, trims, caps and clears the note on one line only", () => {
    addToCart("tab", entry);
    addToCart("tab", { ...entry, modifier_ids: ["m1"] });
    setNote("tab", "key-1", "  less oil  ");
    expect(readCart("tab").map((e) => e.note)).toEqual(["less oil", ""]);
    setNote("tab", "key-1", "x".repeat(300));
    expect(readCart("tab")[0]?.note).toHaveLength(200);
    setNote("tab", "key-1", "");
    expect(readCart("tab")[0]?.note).toBe("");
    setNote("tab", "nope", "ignored");
    expect(readCart("tab").map((e) => e.note)).toEqual(["", ""]);
  });

  it("removes a line when its quantity drops below one", () => {
    addToCart("tab", entry);
    setQty("tab", "key-1", 0);
    expect(readCart("tab")).toEqual([]);
  });

  it("clears storage when emptied and survives corrupt data", () => {
    const { storage } = stubBrowser();
    writeCart("tab", [{ ...entry, key: "k" }]);
    expect(storage.has("restosaas.cart.tab")).toBe(true);
    writeCart("tab", []);
    expect(storage.has("restosaas.cart.tab")).toBe(false);
    storage.set("restosaas.cart.tab", "{not json");
    expect(readCart("tab")).toEqual([]);
  });
});
