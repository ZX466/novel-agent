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

/**
 * Same as `textToParagraphNodes`, but every paragraph is marked with the
 * AI class (`.prose p.ai` marker — accent border + "AI" corner tag). Used
 * when inserting AI-generated text so AI output stays visually distinct
 * from the author's own writing (OpenDesign port, R10).
 *
 * The `class: "ai"` attr requires the AIParagraph extension in the editor
 * (StarterKit's Paragraph drops unknown attributes).
 */
export function aiTextToParagraphNodes(text: string): JSONContent[] {
  return textToParagraphNodes(text).map((node) => ({
    ...node,
    attrs: { ...(node.attrs ?? {}), class: "ai" },
  }));
}

/**
 * Convert stored plain text (paragraphs separated by `\n`/`\n\n`) into
 * simple HTML for `editor.setContent`.
 *
 * The editor saves via `editor.getText()` (plain text, blocks separated by
 * `\n\n`) but `setContent` parses its argument as HTML — raw newlines
 * collapse into one wall of text. Escaping + wrapping each line as a
 * `<p>` restores the paragraph structure on load.
 */
export function textToTipTapHTML(text: string): string {
  if (!text) return "";
  // Cheap guard: already-HTML content (older chapters saved from the
  // editor's original HTML path) passes through untouched.
  if (/<[a-z][\s\S]*>/i.test(text)) return text;
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return escaped
    .split("\n")
    .map((line) => `<p>${line ? line : "<br>"}</p>`)
    .join("");
}
