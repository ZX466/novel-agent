"use client";

import { DefaultChatTransport } from "ai";
import { useChat } from "@ai-sdk/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useProviderConfig } from "@/hooks/use-provider-config";
import { chatEndpoint } from "@/lib/config";
import { loadProviderConfig, ownerAuthHeaders } from "@/lib/settings";

interface AIToolPanelProps {
  /** Called with the generated text once a tool finishes streaming. */
  onInsertIntoEditor: (text: string) => void;
  /** Replace selected text in the editor with AI output. */
  onReplaceInEditor?: (text: string) => void;
  /** Apply outline to document metadata and auto-create chapters. */
  onApplyOutline?: (outlineText: string) => void;
  /** Current editor text to send as context for续写/扩写/重写/降AI. */
  editorText?: string;
  /** Currently selected text in the editor. */
  selectedText?: string;
  /** Current chapter title for context injection. */
  chapterTitle?: string;
  /** Optional novel_id tag to inject into the prompt for RAG retrieval. */
  novelId?: number;
  /** Novel/document title for outline generation context. */
  novelTitle?: string;
  /** Outline text to inject as context for generation/continuation tools. */
  outlineText?: string;
}

type ToolKey = "generate" | "continue" | "expand" | "rewrite" | "deai" | "outline";

interface OutlineFormState {
  genre: string;
  tone: string;
  description: string;
  targetChapters: string;
}

const EMPTY_OUTLINE_FORM: OutlineFormState = {
  genre: "玄幻",
  tone: "热血爽文",
  description: "",
  targetChapters: "",
};

const GENRE_OPTIONS = ["玄幻", "修仙", "都市", "历史", "科幻", "悬疑", "言情", "武侠", "末世", "系统", "其他"];
const TONE_OPTIONS = ["热血爽文", "轻松治愈", "黑暗压抑", "烧脑悬疑", "甜宠", "虐心", "成长励志", "其他"];

const TOOLS: Array<{ key: ToolKey; icon: string; label: string; desc: string }> = [
  { key: "outline",  icon: "📋", label: "生成总纲", desc: "为整部小说生成大纲结构" },
  { key: "generate", icon: "✨", label: "生成正文", desc: "根据总纲生成正文段落" },
  { key: "continue", icon: "✍️", label: "续写",     desc: "从当前末尾续写下文" },
  { key: "expand",   icon: "📝", label: "扩写",     desc: "扩写当前选中或末尾段落" },
  { key: "rewrite",  icon: "🔄", label: "重写",     desc: "重写当前段落" },
  { key: "deai",     icon: "🧹", label: "降AI",     desc: "降低 AI 检测率，重写为更自然的语言" },
];

function buildPrompt(
  tool: ToolKey,
  editorText: string,
  chapterTitle: string,
  novelId?: number,
  selectedText?: string,
  novelTitle?: string,
  outlineText?: string,
  outlineForm?: OutlineFormState,
  customPrompt?: string,
): string {
  const context = editorText.slice(-3000);
  const novelTag = novelId ? `[novel:${novelId}]` : "";
  const titlePart = chapterTitle ? `（章节：${chapterTitle}）` : "";
  const titleContext = novelTitle ? `小说标题：${novelTitle}\n` : "";
  const customPart = customPrompt?.trim() ? `\n补充要求：${customPrompt.trim()}` : "";

  switch (tool) {
    case "outline": {
      const contextPart = editorText.trim()
        ? `\n\n已有正文内容（供参考）：\n${editorText.slice(-3000)}`
        : "";
      const genrePart = outlineForm?.genre ? `体裁：${outlineForm.genre}\n` : "";
      const tonePart  = outlineForm?.tone  ? `风格基调：${outlineForm.tone}\n`  : "";
      const descPart  = outlineForm?.description?.trim()
        ? `故事简介：${outlineForm.description.trim()}\n`
        : "";
      const chapPart  = outlineForm?.targetChapters
        ? `目标章数：${outlineForm.targetChapters}章\n`
        : "";
      return `${novelTag} [task:outline] ${titleContext}${genrePart}${tonePart}${descPart}${chapPart}请为这本小说生成完整的故事大纲，包含主题、核心冲突、主要角色、世界观设定、每章梗概。${contextPart}${customPart}`;
    }
    case "generate": {
      const outlinePart = outlineText
        ? `\n\n故事大纲（请据此生成正文）：\n${outlineText.slice(-6000)}`
        : "";
      return `${novelTag} [task:generate] ${titleContext}根据以下大纲和已写内容，续写新的正文段落${titlePart}。${outlinePart}\n\n当前内容：\n${context}${customPart}`;
    }
    case "continue": {
      const outlinePart = outlineText
        ? `\n\n故事大纲（供参考）：\n${outlineText.slice(-6000)}`
        : "";
      return `${novelTag} [task:continue] ${titleContext}请从以下内容的末尾继续写作，保持风格一致，自然衔接${titlePart}。${outlinePart}\n\n当前内容：\n${context}${customPart}`;
    }
    case "expand": {
      const target = selectedText || context;
      return `${novelTag} [task:rewrite] 请将以下段落进行扩写，增加细节描写和情节发展${titlePart}。\n\n待扩写内容：\n${target}${customPart}`;
    }
    case "rewrite": {
      const target = selectedText || context;
      return `${novelTag} [task:rewrite] 请重写以下段落，改进文笔和表达，保持情节不变${titlePart}。\n\n待重写内容：\n${target}${customPart}`;
    }
    case "deai": {
      const target = selectedText || context;
      return `${novelTag} [task:polish] 请将以下内容改写为更自然的人类写作风格，降低 AI 检测率，保持意思不变${titlePart}。\n\n待处理内容：\n${target}${customPart}`;
    }
  }
}

export function AIToolPanel({
  onInsertIntoEditor,
  onReplaceInEditor,
  onApplyOutline,
  editorText = "",
  selectedText = "",
  chapterTitle = "",
  novelId,
  novelTitle = "",
  outlineText = "",
}: AIToolPanelProps) {
  const { isConfigured, loaded } = useProviderConfig();
  const [activeTool, setActiveTool] = useState<ToolKey | null>(null);

  // Outline generation form — shown inline before sending the prompt.
  const [showOutlineForm, setShowOutlineForm] = useState(false);
  const [outlineForm, setOutlineForm] = useState<OutlineFormState>(EMPTY_OUTLINE_FORM);

  // Optional custom prompt appended to every tool request.
  const [customPrompt, setCustomPrompt] = useState("");
  const [showCustomPrompt, setShowCustomPrompt] = useState(false);

  // Editable copy of the latest generated text (user can tweak before inserting).
  const [editedText, setEditedText] = useState("");
  const wasBusy = useRef(false);

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: chatEndpoint,
        headers: (): Record<string, string> => {
          const cfg = loadProviderConfig();
          const auth = ownerAuthHeaders();
          if (!cfg) return auth;
          return { "X-Provider-Config": JSON.stringify(cfg), ...auth };
        },
      }),
    [],
  );

  const { messages, sendMessage, status, stop, error, setMessages } = useChat({ transport });
  const isBusy = status === "submitted" || status === "streaming";

  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number>(0);
  useEffect(() => {
    if (isBusy) {
      startRef.current = Date.now();
      setElapsed(0);
      const id = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
      return () => clearInterval(id);
    }
    setElapsed(0);
  }, [isBusy]);

  // Latest assistant message text (for live streaming display).
  const latestAssistantText = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") {
        return messages[i].parts
          .filter((p) => p.type === "text")
          .map((p) => (p as { type: string; text: string }).text)
          .join("");
      }
    }
    return "";
  }, [messages]);

  // When generation finishes, copy the result into editedText so the user can tweak it.
  useEffect(() => {
    if (wasBusy.current && !isBusy && latestAssistantText) {
      setEditedText(latestAssistantText);
    }
    wasBusy.current = isBusy;
  }, [isBusy, latestAssistantText]);

  const handleTool = (tool: ToolKey) => {
    if (isBusy) return;
    if (tool === "outline") {
      // Show the outline form instead of firing immediately.
      setShowOutlineForm(true);
      return;
    }
    setActiveTool(tool);
    setEditedText("");
    sendMessage({
      text: buildPrompt(tool, editorText, chapterTitle, novelId, selectedText, novelTitle, outlineText, undefined, customPrompt),
    });
  };

  const handleOutlineSubmit = () => {
    setShowOutlineForm(false);
    setActiveTool("outline");
    setEditedText("");
    sendMessage({
      text: buildPrompt("outline", editorText, chapterTitle, novelId, selectedText, novelTitle, outlineText, outlineForm, customPrompt),
    });
  };

  const handleInsert = () => {
    if (editedText) onInsertIntoEditor(editedText);
  };

  return (
    <aside className="flex flex-col h-full overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Header */}
      <div
        className="px-sp-4 py-sp-3 border-b flex flex-col gap-[3px] shrink-0"
        style={{ background: "var(--surface)", borderColor: "var(--border-subtle)" }}
      >
        <span className="text-[10px] font-semibold uppercase" style={{ color: "var(--fg-tertiary)", letterSpacing: "0.1em" }}>
          AI 工具
        </span>
        <span className="text-[11px]" style={{ color: "var(--muted)" }}>
          生成总纲 → 生成正文 → 续写/扩写/重写
        </span>
      </div>

      {/* API not configured warning */}
      {loaded && !isConfigured && (
        <div
          className="px-sp-4 py-sp-2 text-xs border-b flex items-center gap-sp-2"
          style={{ color: "var(--warn)", background: "oklch(0.74 0.10 85 / 0.06)", borderColor: "oklch(0.74 0.10 85 / 0.12)" }}
        >
          <svg className="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          请先在首页配置 API Key
        </div>
      )}

      {/* Tool buttons */}
      <div className="p-sp-3 flex flex-col gap-sp-1.5 shrink-0">
        {TOOLS.map((tool) => (
          <button
            key={tool.key}
            type="button"
            onClick={() => handleTool(tool.key)}
            disabled={isBusy || !isConfigured}
            className="flex items-center gap-sp-2.5 px-sp-3 py-sp-2 rounded-sm text-left transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: activeTool === tool.key && isBusy ? "var(--accent-bg)" : "transparent",
              color: activeTool === tool.key && isBusy ? "var(--accent)" : "var(--fg-secondary)",
            }}
            onMouseEnter={(e) => { if (!e.currentTarget.disabled) { e.currentTarget.style.background = "var(--surface)"; e.currentTarget.style.color = "var(--fg)"; } }}
            onMouseLeave={(e) => { if (!e.currentTarget.disabled) { e.currentTarget.style.background = activeTool === tool.key && isBusy ? "var(--accent-bg)" : "transparent"; e.currentTarget.style.color = activeTool === tool.key && isBusy ? "var(--accent)" : "var(--fg-secondary)"; } }}
          >
            <span className="text-[14px]">{tool.icon}</span>
            <div className="flex flex-col min-w-0">
              <span className="text-[12px] font-medium leading-[1.3]">{tool.label}</span>
              <span className="text-[10px] leading-[1.3] truncate" style={{ color: "var(--fg-tertiary)" }}>{tool.desc}</span>
            </div>
            {activeTool === tool.key && isBusy && (
              <span className="ml-auto shrink-0">
                <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--accent)" }}>
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Selected text indicator */}
      {selectedText && (
        <div className="px-sp-3 pb-sp-2">
          <div className="text-[10px] px-sp-2 py-sp-1 rounded" style={{ background: "var(--accent-bg)", color: "var(--accent)" }}>
            已选中 {selectedText.length} 字，扩写/重写/降AI 将针对选中内容
          </div>
        </div>
      )}

      {/* Custom prompt toggle + input */}
      <div className="px-sp-3 pb-sp-2 shrink-0">
        <button
          type="button"
          onClick={() => setShowCustomPrompt((v) => !v)}
          className="text-[10px] flex items-center gap-1 transition-colors"
          style={{ color: showCustomPrompt ? "var(--accent)" : "var(--muted)" }}
        >
          <span>{showCustomPrompt ? "▾" : "▸"}</span>
          <span>补充要求（注入到所有工具）</span>
        </button>
        {showCustomPrompt && (
          <textarea
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
            placeholder="例：主角性格要热血，语言风格偏古风，每章不少于3000字…"
            rows={3}
            className="mt-1 w-full px-2 py-1.5 rounded text-[11px] outline-none border resize-none"
            style={{ background: "var(--surface)", borderColor: "var(--border-subtle)", color: "var(--fg)" }}
          />
        )}
      </div>

      {/* Outline generation form — shown when user clicks "生成总纲" */}
      {showOutlineForm && !isBusy && (
        <div
          className="mx-sp-3 mb-sp-2 p-sp-3 rounded border flex flex-col gap-sp-2 shrink-0"
          style={{ background: "var(--surface)", borderColor: "var(--accent)", borderStyle: "dashed" }}
        >
          <span className="text-[11px] font-semibold" style={{ color: "var(--accent)" }}>📋 总纲生成设置</span>
          <div className="flex gap-sp-2">
            <div className="flex flex-col gap-0.5 flex-1">
              <label className="text-[10px]" style={{ color: "var(--muted)" }}>体裁</label>
              <select
                value={outlineForm.genre}
                onChange={(e) => setOutlineForm((f) => ({ ...f, genre: e.target.value }))}
                className="px-1.5 py-1 rounded text-[11px] outline-none border"
                style={{ background: "var(--bg)", borderColor: "var(--border-subtle)", color: "var(--fg)" }}
              >
                {GENRE_OPTIONS.map((g) => <option key={g} value={g}>{g}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-0.5 flex-1">
              <label className="text-[10px]" style={{ color: "var(--muted)" }}>风格基调</label>
              <select
                value={outlineForm.tone}
                onChange={(e) => setOutlineForm((f) => ({ ...f, tone: e.target.value }))}
                className="px-1.5 py-1 rounded text-[11px] outline-none border"
                style={{ background: "var(--bg)", borderColor: "var(--border-subtle)", color: "var(--fg)" }}
              >
                {TONE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>
          <div className="flex flex-col gap-0.5">
            <label className="text-[10px]" style={{ color: "var(--muted)" }}>故事简介（可选）</label>
            <textarea
              value={outlineForm.description}
              onChange={(e) => setOutlineForm((f) => ({ ...f, description: e.target.value }))}
              placeholder="用一两句话描述你的故事核心…"
              rows={2}
              className="px-2 py-1 rounded text-[11px] outline-none border resize-none"
              style={{ background: "var(--bg)", borderColor: "var(--border-subtle)", color: "var(--fg)" }}
            />
          </div>
          <div className="flex flex-col gap-0.5">
            <label className="text-[10px]" style={{ color: "var(--muted)" }}>目标章数（可选）</label>
            <input
              type="number"
              min={1}
              value={outlineForm.targetChapters}
              onChange={(e) => setOutlineForm((f) => ({ ...f, targetChapters: e.target.value }))}
              placeholder="例：30"
              className="px-2 py-1 rounded text-[11px] outline-none border"
              style={{ background: "var(--bg)", borderColor: "var(--border-subtle)", color: "var(--fg)" }}
            />
          </div>
          <div className="flex gap-sp-2 justify-end pt-sp-1">
            <button type="button" onClick={() => setShowOutlineForm(false)}
              className="px-2 py-0.5 rounded text-[11px] border"
              style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}>取消</button>
            <button type="button" onClick={handleOutlineSubmit}
              className="px-3 py-0.5 rounded text-[11px] font-medium"
              style={{ background: "var(--accent)", color: "var(--bg)" }}>开始生成</button>
          </div>
        </div>
      )}

      {/* Divider */}
      <div className="px-sp-4 shrink-0"><div className="border-t" style={{ borderColor: "var(--border-subtle)" }} /></div>

      {/* Result area */}
      <div className="flex-1 overflow-y-auto p-sp-4 min-h-0 flex flex-col">
        {isBusy && (
          <div className="mb-sp-3 flex items-center gap-sp-2 shrink-0">
            <button type="button" onClick={stop}
              className="px-sp-3 py-sp-1.5 rounded-sm text-[11px] font-medium"
              style={{ background: "var(--danger)", color: "white" }}>停止生成</button>
            <span className="text-[10px]" style={{ color: "var(--muted)" }}>
              {activeTool ? TOOLS.find((t) => t.key === activeTool)?.label : "AI"} 生成中…
              {elapsed > 0 && ` ${elapsed}s`}
            </span>
          </div>
        )}
        {error && !isBusy && (
          <div className="mb-sp-3 px-sp-3 py-sp-2 rounded-sm text-[11px]"
            style={{ color: "var(--danger)", background: "oklch(0.60 0.16 25 / 0.08)", border: "1px solid oklch(0.60 0.16 25 / 0.15)" }}>
            AI 服务暂时不可用，请稍后重试
          </div>
        )}

        {/* Streaming display */}
        {isBusy && latestAssistantText && (
          <div className="text-[13px] leading-[1.7] whitespace-pre-wrap flex-1" style={{ color: "var(--fg-secondary)" }}>
            {latestAssistantText}
            <span className="inline-block w-[2px] h-[1em] ml-[1px] align-text-bottom"
              style={{ background: "var(--accent)", animation: "blink 1s step-end infinite" }} />
          </div>
        )}
        {isBusy && !latestAssistantText && (
          <div className="flex-1 flex items-center gap-sp-2" style={{ color: "var(--muted)" }}>
            <div className="flex gap-[3px]">
              {[0, 1, 2].map((i) => (
                <span key={i} className="w-[3px] h-[3px] rounded-full"
                  style={{ background: "var(--accent-muted)", animation: `typing 1.4s infinite ${i * 0.2}s` }} />
              ))}
            </div>
            <span className="text-[11px]">正在生成…</span>
          </div>
        )}

        {/* Editable result textarea — shown after generation completes */}
        {!isBusy && editedText && (
          <textarea
            value={editedText}
            onChange={(e) => setEditedText(e.target.value)}
            className="flex-1 min-h-[120px] w-full px-2 py-2 rounded text-[13px] leading-[1.7] outline-none border resize-none"
            style={{ background: "var(--surface)", borderColor: "var(--border-subtle)", color: "var(--fg-secondary)" }}
          />
        )}

        {/* Empty state */}
        {!isBusy && !editedText && !error && (
          <div className="flex-1 flex flex-col items-center justify-center text-center gap-sp-3" style={{ color: "var(--muted)" }}>
            <svg className="w-10 h-10" style={{ color: "var(--border)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            <p className="text-[12px] max-w-[180px]">点击上方按钮使用 AI 工具，生成内容将显示在此</p>
          </div>
        )}

        {/* Action buttons */}
        {!isBusy && editedText && (
          <div className="pt-sp-3 mt-auto shrink-0 flex flex-col gap-sp-2">
            {activeTool === "outline" ? (
              <button type="button"
                onClick={() => { onApplyOutline?.(editedText); setMessages([]); setActiveTool(null); setEditedText(""); }}
                className="w-full py-sp-2.5 rounded-sm text-[12px] font-medium transition-all"
                style={{ background: "var(--accent)", color: "var(--bg)", letterSpacing: "0.02em" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--accent-hover)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "var(--accent)"; e.currentTarget.style.transform = "translateY(0)"; }}>
                📋 应用大纲（保存并创建章节）
              </button>
            ) : (
              <>
                {selectedText && onReplaceInEditor && (
                  <button type="button" onClick={() => onReplaceInEditor?.(editedText)}
                    className="w-full py-sp-2.5 rounded-sm text-[12px] font-medium border"
                    style={{ borderColor: "var(--accent)", color: "var(--accent)" }}>
                    替换选中文字
                  </button>
                )}
                <button type="button" onClick={handleInsert}
                  className="w-full py-sp-2.5 rounded-sm text-[12px] font-medium transition-all"
                  style={{ background: "var(--accent)", color: "var(--bg)", letterSpacing: "0.02em" }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "var(--accent-hover)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "var(--accent)"; e.currentTarget.style.transform = "translateY(0)"; }}>
                  插入到编辑器
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}