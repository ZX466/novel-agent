"use client";

/**
 * AI-paragraph marker persistence (R10): the editor stores chapters as plain
 * text (`content_text`), so the in-document `class="ai"` markers can't survive
 * a save/load cycle by themselves. Instead, the indices of AI-generated
 * paragraphs are persisted in the chapter's `metadata_json.ai_paragraphs`
 * (number[] — 0-based positions among the reloaded paragraphs) and re-applied
 * when the chapter text is converted back into editor content.
 *
 * Contract notes:
 * - metadata_json is a free-form dict on the backend (no schema change).
 * - The marker is best-effort: indices are clamped/validated on apply, so a
 *   chapter edited between sessions simply loses stale markers (never shifts
 *   them onto the wrong paragraph beyond count bounds).
 */
import type { JSONContent } from "@tiptap/core";

/** Extract the 0-based indices of paragraphs carrying the `ai` class. */
export function collectAiParagraphIndices(doc: JSONContent | undefined): number[] {
  if (!doc?.content) return [];
  return doc.content
    .map((node, i) =>
      node.type === "paragraph" &&
      typeof node.attrs?.class === "string" &&
      node.attrs.class.split(/\s+/).includes("ai")
        ? i
        : -1,
    )
    .filter((i) => i >= 0);
}

/** Build the metadata patch for a chapter save (`ai_paragraphs` only when
 *  non-empty; an empty array clears stale markers). */
export function aiParagraphsMetadata(doc: JSONContent | undefined): Record<string, unknown> {
  const indices = collectAiParagraphIndices(doc);
  return { ai_paragraphs: indices };
}

/** Apply persisted `ai_paragraphs` indices as paragraph classes. Returns a
 *  new JSON doc (immutability — never mutates the input). */
export function applyAiParagraphIndices(
  doc: JSONContent,
  indices: unknown,
): JSONContent {
  if (!Array.isArray(indices) || indices.length === 0 || !doc.content) return doc;
  const set = new Set(
    indices.filter((n): n is number => typeof n === "number" && Number.isInteger(n)),
  );
  let pos = 0;
  const content = doc.content.map((node) => {
    if (node.type !== "paragraph") return node;
    const idx = pos++;
    return set.has(idx)
      ? { ...node, attrs: { ...(node.attrs ?? {}), class: "ai" } }
      : node;
  });
  return { ...doc, content };
}
