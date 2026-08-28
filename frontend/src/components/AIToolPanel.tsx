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

const CONTEXT_DRAFT_ENDPOINT = (novelId: number) => `/v1/chat/draft/${novelId}`;

/**
 * Fetch a completed AI-generation result the backend persisted to Redis.
 * The chat pipeline keeps generating after a mid-stream disconnect and stores
 * the full output under `ai-draft:{novel_id}` (1h TTL). If generation is
 * still running when we first poll, retry with exponential backoff for up
 * to 10 minutes so the user returning mid-generation still gets the complete
 * text - full pipelines (draft->refine->evaluate loop) run several minutes.
 */
async function fetchCompletedDraft(novelId: number): Promise<string> {
  const deadline = Date.now() + 600_000; // 10 min
  let delay = 3000;
  for (;;) {
    try {
      const res = await fetch(CONTEXT_DRAFT_ENDPOINT(novelId), {
        headers: { ...ownerAuthHeaders() },
      });
      if (res.ok) {
        const body = (await res.json()) as { text?: string };
        if (body.text) return body.text;
      }
    } catch {
      // network blip — keep retrying until deadline
    }
    if (Date.now() >= deadline) return "";
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(delay * 2, 30000);
  }
}

/**
 * Trim the outline for chapter-writing prompts to the synopsis of the
 * CURRENT chapter (+ the next one for lead-in), not the whole arc.
 * Writing chapter N only needs "what happens in N and what comes next";
 * injecting the entire outline (theme/characters/every chapter) both
 * dilutes the instruction and multiplies the keywords that trip
 * provider-side content moderation ("blocked" APIError on genre words).
 */
function outlineForPrompt(outlineText: string, chapterTitle?: string): string {
  const CHAP_LINE = /^第[一二三四五六七八九十百千零〇两\d]+章/;
  const lines = outlineText.split("\n");
  const starts: number[] = [];
  for (let i = 0; i < lines.length; i++) {
    if (CHAP_LINE.test(lines[i].trim())) starts.push(i);
  }
  if (starts.length === 0) return outlineText.slice(-6000);

  // Locate the current chapter by matching the editor's chapter title
  // against synopsis headings (fall back to the last two chapters).
  let cur = -1;
  if (chapterTitle) {
    const wanted = chapterTitle.replace(/\s+/g, "");
    cur = starts.findIndex((s) => lines[s].replace(/\s+/g, "").startsWith(wanted));
    if (cur === -1) {
      // Title like「第一章 青石镇的弃儿」may appear as a prefix of the
      // synopsis heading or vice versa; try prefix match either way.
      cur = starts.findIndex((s) => {
        const h = lines[s].replace(/\s+/g, "");
        return h.startsWith(wanted) || wanted.startsWith(h);
      });
    }
  }
  if (cur === -1) {
    const from = Math.max(0, starts.length - 2);
    return lines.slice(starts[from]).join("\n").slice(-6000);
  }
  // Current chapter + next chapter's synopsis (a few hundred chars).
  const from = starts[cur];
  const to = cur + 1 < starts.length ? starts[cur + 1] : lines.length;
  return lines.slice(from, to).join("\n").slice(0, 1500);
}

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
      return `${novelTag} [task:outline] ${titleContext}${genrePart}${tonePart}${descPart}${chapPart}请为这本小说生成完整的故事大纲，包含以下部分：\n`
        + `1. 【主题与核心冲突】1-2句话点明主题与核心矛盾；\n`
        + `2. 【主要角色】逐个列出：姓名、身份、动机、性格、成长弧线（每角色 2-3 行）；\n`
        + `3. 【世界观设定】地理、势力、力量体系等（分条）；\n`
        + `4. 【章节梗概】${chapPart.trim() ? `按${outlineForm?.targetChapters}章逐章列出，` : "逐章列出（8-20章，每章"}每章以"第X章 标题"开头，接 2-3 句该章发生的事、冲突与伏笔。\n`
        + `只输出大纲本身，不要解释、不要复述要求。${contextPart}${customPart}`;
    }
    case "generate": {
      const outlinePart = outlineText
        ? `\n\n本章大纲梗概（请严格据此展开情节，不偏离设定）：\n${outlineForPrompt(outlineText, chapterTitle)}`
        : "";
      return `${novelTag} [task:generate] ${titleContext}请根据故事大纲续写新的正文段落${titlePart}。\n`
        + `要求：\n`
        + `- 目标长度 800-1200 字，一次写一个完整场景（有起承转合）\n`
        + `- 开头自然衔接上一段，不重复已写内容\n`
        + `- 多用具体动作、环境细节、对白与心理活动，避免空泛概括\n`
        + `- 人物言行必须符合既有角色设定与世界观，推进剧情并留下至少一处伏笔\n`
        + `- 结尾停在张力点，方便继续续写\n`
        + `- 正文分段：每个自然段 2-5 句，段间换行，严禁一整段输出\n`
        + `第一行输出当前章节号和标题（${chapterTitle || "第X章 标题"}），空一行后开始正文；除首行外不要任何解释或思考过程。${outlinePart}\n\n当前内容：\n${context}${customPart}`;
    }
    case "continue": {
      const outlinePart = outlineText
        ? `\n\n本章大纲梗概（供参考，保持设定一致）：\n${outlineForPrompt(outlineText, chapterTitle)}`
        : "";
      return `${novelTag} [task:continue] ${titleContext}请从以下内容的末尾继续写作${titlePart}。\n`
        + `要求：\n`
        + `- 目标长度 500-900 字，一次推进一个情节节拍\n`
        + `- 与上文风格、视角、时态保持一致，衔接自然\n`
        + `- 结合已有的人物性格与世界观设定推进，不强行反转\n`
        + `- 正文分段：每个自然段 2-5 句，段间换行，严禁一整段输出\n`
        + `- 直接输出续写正文，不要解释或思考过程。${outlinePart}\n\n当前内容：\n${context}${customPart}`;
    }
    case "expand": {
      const target = selectedText || context;
      return `${novelTag} [task:rewrite] 请将以下段落扩写${titlePart}。\n`
        + `要求：\n`
        + `- 在保持原意与情节不变的前提下，补充感官细节、动作、对白、环境与心理描写\n`
        + `- 扩写后长度约为原文的 2-3 倍\n`
        + `- 不新增与主线无关的支线，不改变人物设定\n`
        + `直接输出扩写后的完整段落，不要解释。\n\n待扩写内容：\n${target}${customPart}`;
    }
    case "rewrite": {
      const target = selectedText || context;
      return `${novelTag} [task:rewrite] 请重写以下段落${titlePart}。\n`
        + `要求：\n`
        + `- 保持情节与信息不变，只改进文笔：句式更流畅、用词更精准、节奏更有张力\n`
        + `- 保持原文视角与风格基调\n`
        + `- 长度与原文相当（约 ±20%）\n`
        + `直接输出重写后的完整段落，不要解释。\n\n待重写内容：\n${target}${customPart}`;
    }
    case "deai": {
      const target = selectedText || context;
      return `${novelTag} [task:polish] 请将以下内容改写为更自然的人类写作风格${titlePart}。\n`
        + `要求：\n`
        + `- 消除明显的 AI 腔：套路化排比、"然而/不禁/仿佛"式高频词、空泛总结\n`
        + `- 用具体、口语化但不失文采的表述替代模板句\n`
        + `- 保持情节与人物设定完全不变\n`
        + `- 长度与原文相当（约 ±20%）\n`
        + `直接输出改写后的完整段落，不要解释。\n\n待处理内容：\n${target}${customPart}`;
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
  // Persisted to localStorage so leaving the editor mid-generation doesn't
  // lose the result — restore it on remount.
  const storageKey = novelId ? `project11:ai-draft:${novelId}` : null;
  const [editedText, setEditedText] = useState(() => {
    if (!storageKey) return "";
    try {
      return window.localStorage.getItem(storageKey) ?? "";
    } catch {
      return "";
    }
  });
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
      clearPending();
    }
    wasBusy.current = isBusy;
  }, [isBusy, latestAssistantText]);

  // Persist the live result (streaming buffer included, not just the finished
  // editedText) so leaving the editor mid-generation doesn't lose it.
  // Never removeItem here: a submission clears the UI copy via setEditedText("")
  // while the model is still thinking (no tokens yet), and wiping storage then
  // would destroy a previously saved draft on a mid-thought exit.
  useEffect(() => {
    if (!storageKey) return;
    const value = editedText || latestAssistantText;
    if (!value) return;
    try {
      window.localStorage.setItem(storageKey, value);
    } catch {
      // localStorage unavailable (private mode etc.) — non-fatal.
    }
  }, [editedText, latestAssistantText, storageKey]);

  // "Generation interrupted" marker: set on submit, cleared once real content
  // lands. If the user leaves while the model is still thinking (no tokens),
  // the draft area would otherwise come back blank with no explanation.
  const pendingKey = storageKey ? `${storageKey}:pending` : null;
  const [interrupted, setInterrupted] = useState(false);
  const [recovering, setRecovering] = useState(false);
  useEffect(() => {
    if (!pendingKey) return;
    let cancelled = false;
    (async () => {
      try {
        if (window.localStorage.getItem(pendingKey)) {
          setInterrupted(true);
          // The backend keeps generating after a mid-stream disconnect and
          // persists the full result to Redis. Poll for it so the user gets
          // the complete text instead of a truncated stream.
          if (novelId) {
            setRecovering(true);
            const full = await fetchCompletedDraft(novelId);
            setRecovering(false);
            if (!cancelled && full) {
              setEditedText(full);
              setInterrupted(false);
              window.localStorage.removeItem(pendingKey);
              try {
                window.localStorage.setItem(storageKey ?? "", full);
              } catch {
                // non-fatal
              }
              return;
            }
          }
          window.localStorage.removeItem(pendingKey); // ack once
        } else {
          window.localStorage.removeItem(pendingKey);
        }
      } catch {
        // localStorage unavailable — non-fatal
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingKey, novelId]);

  const markPending = () => {
    if (!pendingKey) return;
    try {
      window.localStorage.setItem(pendingKey, "1");
    } catch {
      // non-fatal
    }
  };
  const clearPending = () => {
    if (!pendingKey) return;
    try {
      window.localStorage.removeItem(pendingKey);
    } catch {
      // non-fatal
    }
  };

  const handleTool = (tool: ToolKey) => {
    if (isBusy) return;
    if (tool === "outline") {
      // Show the outline form instead of firing immediately.
      setShowOutlineForm(true);
      return;
    }
    setActiveTool(tool);
    setEditedText("");
    markPending();
    sendMessage({
      text: buildPrompt(tool, editorText, chapterTitle, novelId, selectedText, novelTitle, outlineText, undefined, customPrompt),
    });
  };

  const handleOutlineSubmit = () => {
    setShowOutlineForm(false);
    setActiveTool("outline");
    setEditedText("");
    markPending();
    sendMessage({
      text: buildPrompt("outline", editorText, chapterTitle, novelId, selectedText, novelTitle, outlineText, outlineForm, customPrompt),
    });
  };

  const handleInsert = () => {
    if (editedText) {
      onInsertIntoEditor(editedText);
      clearPending();
    }
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
            {recovering ? (
              <>
                <svg className="w-10 h-10 animate-spin" style={{ color: "var(--accent)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
                <p className="text-[12px] max-w-[220px]" style={{ color: "var(--fg-secondary)" }}>
                  后台生成进行中,正在等待完整结果…
                </p>
                <p className="text-[10px] max-w-[240px]" style={{ color: "var(--muted)" }}>
                  离开页面时 AI 仍在后台继续,全流程最多 10 分钟
                </p>
              </>
            ) : interrupted ? (
              <>
                <svg className="w-10 h-10" style={{ color: "var(--warn)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                </svg>
                <p className="text-[12px] max-w-[220px]" style={{ color: "var(--warn)" }}>
                  上次生成在思考时被中断，未产生内容。请重新点击上方工具生成。
                </p>
                <button
                  type="button"
                  onClick={() => { setInterrupted(false); setActiveTool(null); }}
                  className="px-sp-3 py-sp-1.5 rounded-sm text-[11px] font-medium border"
                  style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
                >
                  知道了
                </button>
              </>
            ) : (
              <>
                <svg className="w-10 h-10" style={{ color: "var(--border)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
                <p className="text-[12px] max-w-[180px]">点击上方按钮使用 AI 工具，生成内容将显示在此</p>
              </>
            )}
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