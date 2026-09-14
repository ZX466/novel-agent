/**
 * Outline prompt title-diversity directive (09-14 fix): 1000-chapter volume
 * outlines came back with massive title repetition (神庭之魂×61 — LLM
 * vocabulary exhaustion on long lists). The >40-chapter branch must carry
 * explicit anti-repetition instructions.
 */
import { describe, expect, it } from "vitest";

import { buildPrompt } from "@/components/AIToolPanel";

describe("outline prompt 标题多样性指令", () => {
  const base = {
    editorText: "",
    chapterTitle: "",
    chapterIndex: -1,
    novelId: 1,
    selectedText: "",
    novelTitle: "测试",
    outlineText: "",
    customPrompt: undefined,
  };

  it("volume branch (>40 chapters) demands unique titles", () => {
    const prompt = buildPrompt("outline", base.editorText, base.chapterTitle, base.chapterIndex, base.novelId, base.selectedText, base.novelTitle, base.outlineText, { genre: "玄幻", tone: "热血", description: "", targetChapters: "1000" }, base.customPrompt);
    expect(prompt).toContain("标题不得重复");
    expect(prompt).toContain("50 章");
  });

  it("small-outline branch stays unchanged (no volume directive)", () => {
    const prompt = buildPrompt("outline", base.editorText, base.chapterTitle, base.chapterIndex, base.novelId, base.selectedText, base.novelTitle, base.outlineText, { genre: "玄幻", tone: "热血", description: "", targetChapters: "20" }, base.customPrompt);
    expect(prompt).not.toContain("标题不得重复");
  });
});
