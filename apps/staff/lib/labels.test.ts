import { expect, it } from "vitest";
import { makeLabels } from "./labels";

it("numbers labels from 1", () => {
  expect(makeLabels("B", 3)).toEqual(["B1", "B2", "B3"]);
  expect(makeLabels("T", 0)).toEqual([]);
});
