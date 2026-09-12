import { describe, expect, it } from "vitest";
import { textToParagraphNodes, textToTipTapHTML } from "../insert-text";

describe("textToParagraphNodes", () => {
  it("splits newlines into paragraph nodes", () => {
    const nodes = textToParagraphNodes("第一段\n第二段");
    expect(nodes).toHaveLength(2);
    expect(nodes[0].content?.[0]).toEqual({ type: "text", text: "第一段" });
  });

  it("keeps empty lines as empty paragraphs", () => {
    const nodes = textToParagraphNodes("A\n\nB");
    expect(nodes).toHaveLength(3);
    expect(nodes[1].content).toBeUndefined();
  });
});

describe("textToTipTapHTML", () => {
  it("converts newline-separated text into paragraphs", () => {
    const html = textToTipTapHTML("第一段\n\n第二段");
    expect(html).toBe("<p>第一段</p><p><br></p><p>第二段</p>");
  });

  it("escapes HTML-significant characters", () => {
    expect(textToTipTapHTML("a<b & c")).toBe("<p>a&lt;b &amp; c</p>");
  });

  it("passes through already-HTML content untouched", () => {
    const html = "<p>existing</p>";
    expect(textToTipTapHTML(html)).toBe(html);
  });

  it("returns empty string for empty input", () => {
    expect(textToTipTapHTML("")).toBe("");
  });
});
