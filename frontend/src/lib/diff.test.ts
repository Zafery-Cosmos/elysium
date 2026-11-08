import { describe, expect, it } from "vitest";
import { diffLines, hideMachineBlocks, withContext } from "./diff";

const kinds = (a: string | null, b: string | null) =>
  diffLines(a, b)?.map((row) => (row.kind === "skip" ? "skip" : `${row.kind}:${row.text}`));

describe("diffLines", () => {
  it("shows a new file as additions and a deleted one as deletions", () => {
    expect(kinds(null, "a\nb\n")).toEqual(["add:a", "add:b"]);
    expect(kinds("a\n", null)).toEqual(["del:a"]);
  });

  it("finds a changed line among unchanged ones", () => {
    expect(kinds("a\nb\nc\n", "a\nX\nc\n")).toEqual(["same:a", "del:b", "add:X", "same:c"]);
  });

  it("treats CRLF and LF lines as equal", () => {
    expect(kinds("a\r\nb\r\n", "a\nb\n")).toEqual(["same:a", "same:b"]);
  });

  it("gives up on files too large to compare instead of freezing", () => {
    const before = Array.from({ length: 3000 }, (_, i) => `a${String(i)}`).join("\n");
    const after = Array.from({ length: 3000 }, (_, i) => `b${String(i)}`).join("\n");
    expect(diffLines(before, after)).toBeNull();
  });
});

describe("withContext", () => {
  it("folds what is far from a change", () => {
    const before = Array.from({ length: 20 }, (_, i) => `l${String(i)}`).join("\n");
    const after = before.replace("l10", "changed");
    const rows = withContext(diffLines(before, after) ?? [], 1);
    expect(rows.map((r) => r.kind)).toEqual(["skip", "same", "del", "add", "same", "skip"]);
    expect(rows[0]).toEqual({ kind: "skip", count: 9 });
  });
});

describe("hideMachineBlocks", () => {
  it("removes complete blocks and keeps the explanation", () => {
    expect(
      hideMachineBlocks('Done.\n<elysium-file path="a">\nbody\n</elysium-file>\n<elysium-delete path="b"/>'),
    ).toBe("Done.");
    expect(hideMachineBlocks('<elysium-tool server="s" name="t">{}</elysium-tool>')).toBe("");
  });

  it("hides a block still being streamed", () => {
    expect(hideMachineBlocks('Before\n<elysium-file path="a">\npart')).toBe("Before");
  });

  it("leaves ordinary text alone", () => {
    expect(hideMachineBlocks("a < b  ")).toBe("a < b  ");
  });
});
