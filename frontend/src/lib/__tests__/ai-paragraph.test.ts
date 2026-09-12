import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { AIParagraph } from "@/components/extensions/AIParagraph";

/**
 * The AI-paragraph marker (`.prose p.ai`, OpenDesign port) relies on
 * `class="ai"` surviving a parse→render round trip. StarterKit's Paragraph
 * drops unknown attributes; AIParagraph persists (and whitelists) `class`.
 */
function makeEditor(content: string): Editor {
  return new Editor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        paragraph: false, // replaced by AIParagraph
      }),
      AIParagraph,
    ],
    content,
  });
}

describe("AIParagraph: ai marker round trip", () => {
  let editor: Editor;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    editor?.destroy();
  });

  it("keeps class='ai' on parse", () => {
    editor = makeEditor('<p class="ai">AI写的段落</p><p>人工段落</p>');
    const nodes = editor.getJSON().content ?? [];
    expect(nodes).toHaveLength(2);
    expect(nodes[0].type).toBe("paragraph");
    expect(nodes[0].attrs).toMatchObject({ class: "ai" });
    expect(nodes[1].attrs?.class ?? null).toBeNull();
  });

  it("renders class='ai' back into HTML", () => {
    editor = makeEditor('<p class="ai">AI写的段落</p>');
    expect(editor.getHTML()).toBe('<p class="ai">AI写的段落</p>');
  });

  it("whitelists non-ai classes away", () => {
    editor = makeEditor('<p class="evil-class">随便什么</p>');
    expect(editor.getHTML()).not.toContain("evil-class");
  });

  it("keeps plain paragraphs untouched", () => {
    editor = makeEditor("<p>普通段落</p>");
    expect(editor.getHTML()).toBe("<p>普通段落</p>");
  });

  it("textToParagraphNodes output can be marked as ai", () => {
    // Simulates the AI-insert path: build paragraph nodes with the ai class.
    editor = makeEditor("");
    editor
      .chain()
      .insertContent([
        {
          type: "paragraph",
          attrs: { class: "ai" },
          content: [{ type: "text", text: "AI生成的一行" }],
        },
        {
          type: "paragraph",
          content: [{ type: "text", text: "第二行" }],
        },
      ])
      .run();
    expect(editor.getHTML()).toBe('<p class="ai">AI生成的一行</p><p>第二行</p>');
  });
});
