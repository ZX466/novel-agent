import { describe, expect, it } from "vitest";
import {
  collectAiParagraphIndices,
  aiParagraphsMetadata,
  applyAiParagraphIndices,
} from "../ai-paragraphs";
import type { JSONContent } from "@tiptap/core";

function p(text: string, cls?: string): JSONContent {
  return {
    type: "paragraph",
    ...(cls ? { attrs: { class: cls } } : {}),
    content: text ? [{ type: "text", text }] : undefined,
  };
}

const DOC: JSONContent = {
  type: "doc",
  content: [
    p("第一段（AI）", "ai"),
    p("第二段"),
    p("第三段（AI）", "ai"),
  ],
};

describe("collectAiParagraphIndices", () => {
  it("collects indices of ai-marked paragraphs", () => {
    expect(collectAiParagraphIndices(DOC)).toEqual([0, 2]);
  });

  it("returns empty for docs without ai markers", () => {
    expect(
      collectAiParagraphIndices({ type: "doc", content: [p("a"), p("b")] }),
    ).toEqual([]);
  });

  it("returns empty for undefined/empty docs", () => {
    expect(collectAiParagraphIndices(undefined)).toEqual([]);
    expect(collectAiParagraphIndices({ type: "doc" })).toEqual([]);
  });
});

describe("aiParagraphsMetadata", () => {
  it("builds the metadata patch", () => {
    expect(aiParagraphsMetadata(DOC)).toEqual({ ai_paragraphs: [0, 2] });
  });

  it("clears stale markers with an empty array", () => {
    expect(aiParagraphsMetadata({ type: "doc", content: [p("x")] })).toEqual({
      ai_paragraphs: [],
    });
  });
});

describe("applyAiParagraphIndices", () => {
  it("marks the persisted indices with the ai class", () => {
    const out = applyAiParagraphIndices(
      { type: "doc", content: [p("a"), p("b"), p("c")] },
      [1],
    );
    expect(out.content?.[1].attrs).toMatchObject({ class: "ai" });
    expect(out.content?.[0].attrs?.class).toBeUndefined();
  });

  it("clamps out-of-bounds indices safely (no crash, no mis-marking)", () => {
    const out = applyAiParagraphIndices(
      { type: "doc", content: [p("a")] },
      [0, 5, -1, 1.5, "x"],
    );
    expect(out.content?.[0].attrs).toMatchObject({ class: "ai" });
    expect(out.content).toHaveLength(1);
  });

  it("returns the doc unchanged for empty/invalid indices", () => {
    const doc: JSONContent = { type: "doc", content: [p("a")] };
    expect(applyAiParagraphIndices(doc, [])).toBe(doc);
    expect(applyAiParagraphIndices(doc, "bogus")).toBe(doc);
  });

  it("does not mutate the input doc", () => {
    const doc: JSONContent = { type: "doc", content: [p("a"), p("b")] };
    const snapshot = JSON.stringify(doc);
    applyAiParagraphIndices(doc, [0]);
    expect(JSON.stringify(doc)).toBe(snapshot);
  });
});
