"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { chatEndpoint } from "@/lib/config";
import { loadProviderConfig, ownerAuthHeaders } from "@/lib/settings";

interface AssistantMessage {
  role: "user" | "assistant";
  text: string;
}

interface AssistantPanelProps {
  /** Insert an AI reply into the editor. */
  onInsertIntoEditor: (text: string) => void;
  /** Current chapter id for "selected" context mode. */
  activeChapterId?: number | null;
  /** Novel/document id for context scoping. */
  novelId?: number;
  /** Current chapter title (display only). */
  chapterTitle?: string;
}

const CONTEXT_HINT =
  "我是你的 AI 编剧。我会参考当前章节（或全文）上下文回答你的创作问题，回复可直接插入正文。";

/**
 * F1 AI 对话助手 — multi-turn chat with work context injection.
 *
 * Protocol (Round 4, approved): POST /v1/chat with `task_type=assistant`
 * plus `context_doc_id` / `context_chapter_ids` / `context_mode`
 * (selected = current chapter, full = whole novel).
 */
export function AssistantPanel({
  onInsertIntoEditor,
  activeChapterId,
  novelId,
  chapterTitle,
}: AssistantPanelProps) {
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contextFull, setContextFull] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const hasContext = Boolean(activeChapterId) || contextFull;

  // Scroll to bottom on new messages.
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streaming]);

  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    const next: AssistantMessage[] = [...messages, { role: "user", text }];
    setMessages(next);
    setInput("");
    setError(null);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const cfg = loadProviderConfig();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...ownerAuthHeaders(),
    };
    if (cfg) headers["X-Provider-Config"] = JSON.stringify(cfg);

    try {
      const res = await fetch(chatEndpoint, {
        method: "POST",
        headers,
        signal: controller.signal,
        body: JSON.stringify({
          messages: next.map((m) => ({ role: m.role, content: m.text })),
          task_type: "assistant",
          context_doc_id: novelId,
          context_chapter_ids: contextFull ? undefined : activeChapterId ? [activeChapterId] : undefined,
          context_mode: contextFull ? "full" : "selected",
        }),
      });
      if (!res.ok) {
        let detail = "";
        try {
          const body = (await res.json()) as { detail?: unknown };
          detail =
            typeof body?.detail === "string"
              ? body.detail
              : Array.isArray(body?.detail)
                ? (body.detail as Array<{ msg?: unknown }>).map((d) => String(d?.msg ?? "")).filter(Boolean).join("；")
                : `HTTP ${res.status}`;
        } catch {
          detail = `HTTP ${res.status}`;
        }
        setError(detail || "请求失败");
        setStreaming(false);
        return;
      }

      // Stream AI SDK v5 UI Message Stream (SSE): text-delta / error / [DONE].
      const reader = res.body?.getReader();
      if (!reader) {
        setError("无法读取响应流");
        setStreaming(false);
        return;
      }
      const decoder = new TextDecoder();
      let buffer = "";
      let assistantText = "";

      const flush = () => {
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const evt of events) {
          for (const line of evt.split("\n")) {
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (!payload || payload === "[DONE]") continue;
            try {
              const parsed = JSON.parse(payload) as { type?: string; delta?: string; detail?: string };
              if (parsed.type === "text-delta" && typeof parsed.delta === "string") {
                assistantText += parsed.delta;
                setMessages((prev) => {
                  const copy = [...prev];
                  copy[copy.length - 1] = { role: "assistant", text: assistantText };
                  return copy;
                });
              } else if (parsed.type === "error" && parsed.detail) {
                setError(parsed.detail);
              }
            } catch {
              // ignore non-JSON SSE lines
            }
          }
        }
      };

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        flush();
      }
      flush(); // tail
      if (!assistantText) {
        setMessages((prev) => [...prev, { role: "assistant", text: "(未返回内容，请检查配置或重试)" }]);
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : "网络错误");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  };

  const stop = () => {
    abortRef.current?.abort();
  };

  const latestAssistant = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return messages[i].text;
    }
    return "";
  }, [messages]);

  return (
    <aside className="flex flex-col h-full overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Header */}
      <div
        className="px-sp-4 py-sp-3 border-b flex flex-col gap-[3px] shrink-0"
        style={{ background: "var(--surface)", borderColor: "var(--border-subtle)" }}
      >
        <span className="text-[10px] font-semibold uppercase" style={{ color: "var(--fg-tertiary)", letterSpacing: "0.1em" }}>
          AI 编剧
        </span>
        <span className="text-[11px]" style={{ color: "var(--muted)" }}>
          多轮对话 · 自动携带作品上下文
        </span>
      </div>

      {/* Context toggle */}
      <div className="px-sp-3 py-sp-1.5 border-b flex items-center gap-sp-2 shrink-0" style={{ borderColor: "var(--border-subtle)" }}>
        <button
          type="button"
          onClick={() => setContextFull((v) => !v)}
          title="对话参考范围"
          className="px-sp-2 py-[2px] rounded-sm text-[10px] font-medium border transition-colors"
          style={{
            borderColor: contextFull ? "var(--accent-muted)" : "var(--border)",
            background: contextFull ? "var(--accent-bg)" : "transparent",
            color: contextFull ? "var(--accent)" : "var(--fg-tertiary)",
          }}
        >
          {contextFull ? "参考全文" : "参考当前章节"}
        </button>
        <span className="text-[10px] truncate" style={{ color: "var(--muted)" }}>
          {hasContext ? (contextFull ? "全部章节" : chapterTitle || "当前章节") : "（无可参考章节）"}
        </span>
      </div>

      {/* Messages */}
      <div ref={listRef} className="flex-1 overflow-y-auto p-sp-3 flex flex-col gap-sp-2.5 min-h-0">
        {messages.length === 0 && !streaming && (
          <div className="text-[11px] leading-relaxed px-sp-2 py-sp-2" style={{ color: "var(--muted)" }}>
            {CONTEXT_HINT}
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className="flex flex-col max-w-[92%]"
            style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start" }}
          >
            <div
              className="px-sp-3 py-sp-2 text-[12px] leading-[1.6] whitespace-pre-wrap"
              style={{
                background: m.role === "user" ? "var(--accent)" : "var(--surface)",
                color: m.role === "user" ? "var(--bg)" : "var(--fg-secondary)",
                borderRadius: "var(--radius-sm)",
                border: m.role === "user" ? "none" : "1px solid var(--border-subtle)",
              }}
            >
              {m.text}
            </div>
            {m.role === "assistant" && m.text.length > 0 && !(i === messages.length - 1 && streaming) && (
              <button
                type="button"
                onClick={() => onInsertIntoEditor(m.text)}
                className="self-end mt-sp-1 text-[10px] font-medium px-sp-2 py-[2px] rounded-sm border transition-colors"
                style={{ borderColor: "var(--accent-muted)", color: "var(--accent)" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--accent-bg)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                插入到正文
              </button>
            )}
          </div>
        ))}
        {streaming && (
          <div className="flex items-center gap-sp-2 text-[11px]" style={{ color: "var(--muted)" }}>
            <span className="w-[5px] h-[5px] rounded-full" style={{ background: "var(--accent)", animation: "pulse 1.2s infinite" }} />
            AI 编剧思考中…
          </div>
        )}
        {error && (
          <div
            className="text-[11px] px-sp-3 py-sp-2 rounded-md"
            style={{ color: "var(--danger)", background: "oklch(0.60 0.16 25 / 0.08)", border: "1px solid oklch(0.60 0.16 25 / 0.15)" }}
          >
            {error}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="px-sp-3 py-sp-2.5 border-t shrink-0" style={{ background: "var(--surface)", borderColor: "var(--border-subtle)" }}>
        <div className="flex gap-sp-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder="问 AI 编剧：这段情节怎么发展更合理？"
            rows={2}
            className="flex-1 px-sp-3 py-sp-2 border rounded-md text-[12px] outline-none resize-none"
            style={{ background: "var(--bg)", borderColor: "var(--border)", color: "var(--fg)", lineHeight: "1.5" }}
          />
          {streaming ? (
            <button
              type="button"
              onClick={stop}
              className="w-9 h-9 flex items-center justify-center rounded-md shrink-0"
              style={{ background: "var(--danger)", color: "white" }}
              title="停止"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <rect x="4" y="4" width="16" height="16" rx="2" />
              </svg>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void send()}
              disabled={!input.trim() || !hasContext}
              className="w-9 h-9 flex items-center justify-center rounded-md shrink-0 transition-all disabled:opacity-30"
              style={{ background: "var(--accent)", color: "var(--bg)" }}
              title={hasContext ? "发送" : "请先创建章节"}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          )}
        </div>
        <p className="text-[9px] mt-1" style={{ color: "var(--fg-tertiary)" }}>
          {latestAssistant && !streaming ? "每条回复下方可插入正文 · " : ""}Enter 发送，Shift+Enter 换行
        </p>
      </div>
    </aside>
  );
}
