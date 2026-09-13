/**
 * parseOutlineChapters — outline → chapter entries parsing (R10-⑨ fixes).
 *
 * Deployed 09-13 regression: the outline LLM loves markdown decoration
 * (`**第一章 张三**`, `### 第1章`, `1. 第一章`, `【第一章】`), and every
 * decorated form silently produced 0 entries → 0 chapters created while
 * entity extraction still ran, leaving a novel with lore but no chapters.
 */
import { describe, expect, it } from "vitest";

import { parseOutlineChapters } from "@/hooks/use-outline-workflows";

describe("parseOutlineChapters", () => {
  it("parses plain 第X章 lines", () => {
    const entries = parseOutlineChapters("第一章 张三入宗\n张三拜入青云宗。\n第二章 修炼突破\n苦修三月。");
    expect(entries).toHaveLength(2);
    expect(entries[0].title).toContain("张三入宗");
    expect(entries[0].summary).toContain("青云宗");
  });

  it("parses arabic-numbered 第1章 lines", () => {
    const entries = parseOutlineChapters("第1章 开端\n第2章 转折");
    expect(entries).toHaveLength(2);
    expect(entries[1].title).toContain("转折");
  });

  it("parses markdown bold-wrapped headings", () => {
    const entries = parseOutlineChapters("**第一章 张三入宗**\n**第2章 修炼突破**");
    expect(entries).toHaveLength(2);
    expect(entries[0].title).toContain("张三入宗");
  });

  it("parses markdown heading markers before 第X章", () => {
    const entries = parseOutlineChapters("### 第一章 入门\n### 第二章 突破");
    expect(entries).toHaveLength(2);
  });

  it("parses list-numbered chinese headings (1. 第一章)", () => {
    const entries = parseOutlineChapters("1. 第一章 张三入宗\n   张三在青云宗拜入门下。\n2. 第二章 修炼突破");
    expect(entries).toHaveLength(2);
    expect(entries[0].title).not.toMatch(/^1\./);
  });

  it("parses bracket-decorated headings (【第一章】)", () => {
    const entries = parseOutlineChapters("【第一章】张三入宗\n【第2章】修炼突破");
    expect(entries).toHaveLength(2);
    expect(entries[0].title).toContain("张三入宗");
  });

  it("returns empty for an outline with no chapter lines", () => {
    expect(parseOutlineChapters("【主题与核心冲突】\n生存与人性。\n【主要角色】\n陈默。")).toEqual([]);
  });

  it("does not treat prose mentioning 第3章 mid-sentence as a heading", () => {
    const entries = parseOutlineChapters("他在第三章就死了，这是回忆。\n【主要角色】\n陈默的童年。");
    expect(entries).toEqual([]);
  });

  it("skips 卷 headings but keeps chapters under them", () => {
    const text = "第一卷 崛起\n第一章 入门\n第一章(重复)突破\n第二卷 深渊\n第三章 下潜";
    const entries = parseOutlineChapters(text);
    expect(entries.length).toBeGreaterThanOrEqual(3);
  });
});
