/**
 * Convert plain text into TipTap paragraph nodes.
 *
 * TipTap's `insertContent(string)` parses its argument as HTML, so raw
 * newlines in plain text are collapsed into a single run — multi-paragraph
 * AI output lands in the editor as one wall of text (R9-⑤). Passing an
 * array of nodes instead preserves every `\n` as its own paragraph; empty
 * lines become empty paragraphs so the original blank-line separation is
 * visually restored.
 *
 * R10-⑤: LLMs often emit 3-4 consecutive `\n` between scenes; each blank
 * line used to become its own empty `<p>`, stacking a huge visual gap.
 * Runs of 2+ blank lines now collapse into a single empty paragraph.
 */
import type { JSONContent } from "@tiptap/core";

export function textToParagraphNodes(text: string): JSONContent[] {
  const lines = text.split("\n");
  const nodes: JSONContent[] = [];
  let pendingBlanks = 0;
  for (const line of lines) {
    if (line.trim() === "") {
      pendingBlanks++;
      continue;
    }
    if (nodes.length > 0 && pendingBlanks > 0) {
      // One empty paragraph between blocks, regardless of blank-line count.
      nodes.push({ type: "paragraph", content: undefined });
    }
    pendingBlanks = 0;
    nodes.push({
      type: "paragraph",
      content: [{ type: "text", text: line }],
    });
  }
  // Trailing blanks never produce paragraphs (nothing to separate).
  return nodes;
}

/**
 * Same as `textToParagraphNodes`, but every paragraph is marked with the
 * AI class (`.ProseMirror p.ai` marker — accent border + "AI" corner tag).
 * Used when inserting AI-generated text so AI output stays visually distinct
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
 *
 * R10-⑤: 2+ consecutive blank lines collapse into one empty `<p>` so a
 * model's scene-break `\n\n\n\n` doesn't stack several empty paragraphs
 * of vertical gap.
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
  const lines = escaped.split("\n");
  const parts: string[] = [];
  let pendingBlanks = 0;
  for (const line of lines) {
    if (line.trim() === "") {
      pendingBlanks++;
      continue;
    }
    if (parts.length > 0 && pendingBlanks > 0) {
      parts.push("<p><br></p>");
    }
    pendingBlanks = 0;
    parts.push(`<p>${line}</p>`);
  }
  return parts.join("");
}
