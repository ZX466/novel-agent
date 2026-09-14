/**
 * Rewrite-family surrounding context (09-14): expand/rewrite/deai
 * previously sent ONLY the target text — rewriting a line of dialogue
 * without knowing who was speaking invited drift. The prompt must carry
 * a reference-only 上下文参考 block with text before/after the selection,
 * and omit it when there are no surroundings.
 */
import { describe, expect, it } from "vitest";

import { buildPrompt } from "@/components/AIToolPanel";

describe("rewrite-family 上下文参考", () => {
  it("rewrite with selection includes before/after context", () => {
    const editorText =
      "前文。林昭把剑横在膝上，盯着火堆。\n你要重写的那句话。\n后文。风把灰烬卷起。";
    const prompt = buildPrompt(
      "rewrite", editorText, "第1章 夜行", 0, 1,
      "你要重写的那句话。", "测试", "", undefined,
    );
    expect(prompt).toContain("上下文参考");
    expect(prompt).toContain("林昭把剑横在膝上"); // before selection
    expect(prompt).toContain("风把灰烬卷起");     // after selection
    expect(prompt).toContain("禁止输出或复述");    // reference-only guard
    expect(prompt).toContain("你要重写的那句话");  // target still present
  });

  it("expand with selection includes surrounding context", () => {
    const editorText = "开头一句。\n选中扩写的段落。\n结尾一句。";
    const prompt = buildPrompt(
      "expand", editorText, "第1章 夜行", 0, 1,
      "选中扩写的段落。", "测试", "", undefined,
    );
    expect(prompt).toContain("上下文参考");
    expect(prompt).toContain("开头一句");
    expect(prompt).toContain("结尾一句");
  });

  it("deai with selection includes surrounding context", () => {
    const editorText = "前情。\nAI 腔很重的句子。\n后续。";
    const prompt = buildPrompt(
      "deai", editorText, "第1章 夜行", 0, 1,
      "AI 腔很重的句子。", "测试", "", undefined,
    );
    expect(prompt).toContain("上下文参考");
    expect(prompt).toContain("前情");
    expect(prompt).toContain("后续");
  });

  it("omits the block when selection is at the very start", () => {
    const prompt = buildPrompt(
      "rewrite", "选中在开头。后面还有内容。", "第1章", 0, 1,
      "选中在开头。", "测试", "", undefined,
    );
    expect(prompt).not.toContain("上下文参考");
  });

  it("omits the block when editor text is empty", () => {
    const prompt = buildPrompt(
      "rewrite", "", "第1章", 0, 1, "", "测试", "", undefined,
    );
    expect(prompt).not.toContain("上下文参考");
  });

  it("no-selection fallback (end-of-text target) adds no before-context", () => {
    // Target = last 3000 chars, which starts at pos 0 → nothing before it.
    const editorText = "只有一段不算太长的正文。";
    const prompt = buildPrompt(
      "rewrite", editorText, "第1章", 0, 1, "", "测试", "", undefined,
    );
    expect(prompt).not.toContain("上下文参考");
    // Target itself is still the payload.
    expect(prompt).toContain("只有一段不算太长的正文。");
  });
});
