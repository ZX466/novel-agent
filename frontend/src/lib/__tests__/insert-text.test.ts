import { describe, expect, it } from "vitest";
import { aiTextToParagraphNodes, textToParagraphNodes, textToTipTapHTML } from "../insert-text";

describe("textToParagraphNodes — blank-line collapsing", () => {
  it("collapses 2+ consecutive blank lines into a single empty paragraph", () => {
    // AI output commonly emits 3-4 \n between scenes; each blank line used to
    // become its own empty <p>, stacking up a huge visual gap (R10-⑤).
    const nodes = textToParagraphNodes("第一段\n\n\n\n第二段");
    expect(nodes).toHaveLength(3);
    expect(nodes[0].content?.[0]).toEqual({ type: "text", text: "第一段" });
    expect(nodes[1].content).toBeUndefined(); // single collapsed empty para
    expect(nodes[2].content?.[0]).toEqual({ type: "text", text: "第二段" });
  });

  it("keeps a single blank line as exactly one empty paragraph", () => {
    const nodes = textToParagraphNodes("甲\n\n乙");
    expect(nodes).toHaveLength(3);
    expect(nodes[1].content).toBeUndefined();
  });

  it("leaves text without blank lines untouched", () => {
    const nodes = textToParagraphNodes("甲\n乙");
    expect(nodes).toHaveLength(2);
    expect(nodes.every((n) => n.content !== undefined || n.type === "paragraph")).toBe(true);
  });

  it("aiTextToParagraphNodes keeps the ai class after collapsing", () => {
    const nodes = aiTextToParagraphNodes("甲\n\n\n\n乙");
    expect(nodes).toHaveLength(3);
    expect(nodes[0].attrs).toMatchObject({ class: "ai" });
    expect(nodes[2].attrs).toMatchObject({ class: "ai" });
  });
});

describe("textToTipTapHTML — blank-line collapsing", () => {
  it("collapses multiple blank lines into one empty <p>", () => {
    const html = textToTipTapHTML("第一段\n\n\n\n\n第二段");
    expect(html).toBe("<p>第一段</p><p><br></p><p>第二段</p>");
  });

  it("single blank line still yields one empty <p>", () => {
    expect(textToTipTapHTML("甲\n\n乙")).toBe("<p>甲</p><p><br></p><p>乙</p>");
  });
});
