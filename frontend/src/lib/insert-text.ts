/**
 * Convert plain text into TipTap paragraph nodes.
 *
 * TipTap's `insertContent(string)` parses its argument as HTML, so raw
 * newlines in plain text are collapsed into a single run — multi-paragraph
 * AI output lands in the editor as one wall of text (R9-⑤). Passing an
 * array of nodes instead preserves every `\n` as its own paragraph; empty
 * lines become empty paragraphs so the original blank-line separation is
 * visually restored.
 */
import type { JSONContent } from "@tiptap/core";

export function textToParagraphNodes(text: string): JSONContent[] {
  return text.split("\n").map((line) => ({
    type: "paragraph",
    content: line ? [{ type: "text", text: line }] : undefined,
  }));
}
