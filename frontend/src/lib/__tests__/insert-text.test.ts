import { describe, expect, it } from "vitest";
import { textToParagraphNodes } from "../insert-text";

describe("textToParagraphNodes", () => {
  it("splits multi-paragraph text into separate paragraph nodes", () => {
    const nodes = textToParagraphNodes("第一段\n\n第三段");
    expect(nodes).toHaveLength(3);
    expect(nodes[0].content).toEqual([{ type: "text", text: "第一段" }]);
    // Blank line becomes an empty paragraph (no content) — preserves visual separation.
    expect(nodes[1].content).toBeUndefined();
    expect(nodes[2].content).toEqual([{ type: "text", text: "第三段" }]);
  });

  it("maps single newlines to paragraph breaks", () => {
    const nodes = textToParagraphNodes("A\nB\nC");
    expect(nodes).toHaveLength(3);
    expect(nodes.map((n) => n.content?.[0]?.text)).toEqual(["A", "B", "C"]);
  });

  it("returns one empty paragraph for empty input", () => {
    const nodes = textToParagraphNodes("");
    expect(nodes).toHaveLength(1);
    expect(nodes[0].type).toBe("paragraph");
    expect(nodes[0].content).toBeUndefined();
  });

  it("handles leading/trailing blank lines", () => {
    const nodes = textToParagraphNodes("\n正文\n");
    expect(nodes).toHaveLength(3);
    expect(nodes[0].content).toBeUndefined();
    expect(nodes[1].content).toEqual([{ type: "text", text: "正文" }]);
    expect(nodes[2].content).toBeUndefined();
  });
});
