import { describe, expect, it } from "vitest";
import { addFiles, formatSize, isSupported, MAX_FILE_BYTES, MAX_FILES, move } from "./menu-files";

const f = (name: string, size = 1000, type = "") => ({ name, size, type });

describe("menu file checks", () => {
  it("accepts pdf, jpg, jpeg and png by extension or type", () => {
    expect(isSupported(f("Menu.PDF"))).toBe(true);
    expect(isSupported(f("a.jpeg"))).toBe(true);
    expect(isSupported(f("photo", 1, "image/png"))).toBe(true);
    expect(isSupported(f("notes.txt"))).toBe(false);
    expect(isSupported(f("scan.heic"))).toBe(false);
  });

  it("keeps order and explains what was left out", () => {
    const { files, problems } = addFiles([f("a.jpg")], [f("b.png"), f("c.txt"), f("d.jpg", 0), f("e.jpg", MAX_FILE_BYTES + 1)]);
    expect(files.map((x) => x.name)).toEqual(["a.jpg", "b.png"]);
    expect(problems).toHaveLength(3);
    expect(problems[0]).toContain("c.txt");
    expect(problems[2]).toContain("too large");
  });

  it("stops at the file limit", () => {
    const many = Array.from({ length: MAX_FILES }, (_, i) => f(`p${i}.jpg`));
    const { files, problems } = addFiles(many, [f("extra.jpg")]);
    expect(files).toHaveLength(MAX_FILES);
    expect(problems[0]).toContain("extra.jpg");
  });

  it("moves pages without mutating and ignores impossible moves", () => {
    const list = ["a", "b", "c"];
    expect(move(list, 0, 1)).toEqual(["b", "a", "c"]);
    expect(move(list, 0, -1)).toBe(list);
    expect(move(list, 2, 3)).toBe(list);
    expect(list).toEqual(["a", "b", "c"]);
  });

  it("formats sizes", () => {
    expect(formatSize(500)).toBe("1 KB");
    expect(formatSize(2_500_000)).toBe("2.5 MB");
  });
});
