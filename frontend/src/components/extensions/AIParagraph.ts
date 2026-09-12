"use client";

/**
 * AI-aware Paragraph extension: identical to StarterKit's Paragraph but
 * persists the HTML `class` attribute through parse→render, so AI-inserted
 * paragraphs carry `class="ai"` and render with the AI marker styling
 * (`.prose p.ai` — accent left border + "AI" corner tag, OpenDesign port).
 *
 * R10 third batch: wires the frontend AI marker to actual editor content.
 * `class` only (whitelisted) — no arbitrary attribute injection.
 *
 * NOTE: StarterKit must be configured with `paragraph: false` when this
 * extension is used (one node type per name).
 */
import { mergeAttributes, Node } from "@tiptap/core";

export const AIParagraph = Node.create({
  name: "paragraph",
  priority: 1000, // must win over any other paragraph definition
  addOptions() {
    return { HTMLAttributes: {} };
  },
  group: "block",
  content: "inline*",
  parseHTML() {
    return [{ tag: "p" }];
  },
  addAttributes() {
    return {
      class: {
        default: null,
        parseHTML: (element) => element.getAttribute("class"),
        // Whitelist: only the ai marker class survives a round trip.
        renderHTML: (attributes) => {
          const cls = attributes.class;
          if (typeof cls === "string" && cls.split(/\s+/).includes("ai")) {
            return { class: "ai" };
          }
          return {};
        },
      },
    };
  },
  renderHTML({ HTMLAttributes }) {
    return ["p", mergeAttributes(this.options.HTMLAttributes, HTMLAttributes), 0];
  },
  addCommands() {
    return {
      setParagraph: () => ({ commands }) => commands.setNode(this.name),
    };
  },
  addKeyboardShortcuts() {
    return {
      "Mod-Alt-0": () => this.editor.commands.setParagraph(),
    };
  },
});
