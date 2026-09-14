/**
 * 09-14 四工具小项二条：
 *
 * 1. 无选中常驻目标提示 — 扩写/重写/降AI 不选中时目标是「章节末尾
 *    3000 字」，此前面板只在有选中时提示，静默兜底易误伤。
 * 2. AI 腔密度计 — 纯规则检测（高频词表），对降AI 工具的生成结果
 *    展示「AI 腔密度 前→后」，让效果可度量。不改 LLM 成本。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import React from "react";

import { aiToneDensity, AIToolPanel } from "@/components/AIToolPanel";

// useChat is stubbed to keep the component in its idle state.
const sendMessage = vi.fn();
vi.mock("@/hooks/use-chat", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useChat: () => ({
    messages: [],
    sendMessage,
    status: "ready",
    stop: vi.fn(),
    error: null,
    setMessages: vi.fn(),
  }),
}));

vi.mock("@/hooks/use-provider-config", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useProviderConfig: () => ({ isConfigured: true, loaded: true }),
}));

describe("aiToneDensity", () => {
  it("counts template phrases per 1000 chars", () => {
    const text = "然而他不禁停下了脚步。仿佛一切都在瞬间崩塌，然而她没有回头。".repeat(20);
    const d = aiToneDensity(text);
    expect(d).toBeGreaterThan(0);
  });

  it("clean prose scores near zero", () => {
    const d = aiToneDensity("林昭把剑横在膝上，盯着火堆。风把灰烬卷起，落在他肩头。".repeat(30));
    expect(d).toBeLessThan(1);
  });

  it("empty text → 0", () => {
    expect(aiToneDensity("")).toBe(0);
  });
});

describe("AIToolPanel 无选中目标提示", () => {
  beforeEach(() => {
    cleanup();
    window.localStorage.clear();
  });

  function renderPanel(editorText: string) {
    return render(
      <AIToolPanel
        onInsertIntoEditor={vi.fn()}
        onReplaceInEditor={vi.fn()}
        editorText={editorText}
        novelId={1}
        novelTitle="测试"
      />,
    );
  }

  it("shows persistent end-of-text target hint when nothing selected", () => {
    renderPanel("这是一段不算太短的正文内容。");
    expect(screen.getByText(/将处理章节末尾/)).toBeInTheDocument();
  });

  it("selected state keeps the selection hint (not the end-of-text one)", () => {
    render(
      <AIToolPanel
        onInsertIntoEditor={vi.fn()}
        onReplaceInEditor={vi.fn()}
        editorText="正文。"
        selectedText="选中的句子"
        novelId={1}
      />,
    );
    expect(screen.getByText(/已选中/)).toBeInTheDocument();
    expect(screen.queryByText(/将处理章节末尾/)).not.toBeInTheDocument();
  });

  it("outline/continue-only tools do not show the rewrite-family hint", () => {
    // Empty editor → rewrite family would have no target; no hint either.
    renderPanel("");
    expect(screen.queryByText(/将处理章节末尾/)).not.toBeInTheDocument();
  });
});
