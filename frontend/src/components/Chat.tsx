"use client";

import { useChat } from "@ai-sdk/react";
import { FormEvent, useMemo, useState } from "react";

import { PerfChatTransport, type PipelinePerf } from "@/lib/perf-transport";

import { useProviderConfig } from "@/hooks/use-provider-config";
import { chatEndpoint } from "@/lib/config";
import { loadProviderConfig, ownerAuthHeaders } from "@/lib/settings";

interface ChatProps {
  onInsertIntoEditor?: (text: string) => void;
}

export function Chat({ onInsertIntoEditor }: ChatProps) {
  const { isConfigured, loaded } = useProviderConfig();
  const [lastPerf, setLastPerf] = useState<PipelinePerf | null>(null);

  const transport = useMemo(
    () =>
      new PerfChatTransport({
        api: chatEndpoint,
        headers: (): Record<string, string> => {
          const cfg = loadProviderConfig();
          const auth = ownerAuthHeaders();
          if (!cfg) return auth;
          return { "X-Provider-Config": JSON.stringify(cfg), ...auth };
        },
        onPerf: (perf) => setLastPerf(perf),
      }),
    [],
  );

  const { messages, sendMessage, status, error, stop } = useChat({ transport });
  const [input, setInput] = useState("");

  const isBusy = status === "submitted" || status === "streaming";
  const sendDisabled = isBusy || !input.trim() || (loaded && !isConfigured);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || isBusy || !isConfigured) return;
    sendMessage({ text });
    setInput("");
  };

  const collectMessageText = (parts: Array<{ type: string; text?: string }>): string => {
    return parts
      .filter((p) => p.type === "text" && typeof p.text === "string")
      .map((p) => p.text as string)
      .join("");
  };

  const errorMessage = error ? "Pipeline 出错，请重试" : "";

  return (
    <section className="chat-panel flex flex-col h-full overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Chat header */}
      <div
        className="px-sp-5 py-sp-4 border-b flex flex-col gap-[3px] shrink-0"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
        }}
      >
        <span
          className="text-[10px] font-semibold uppercase"
          style={{ color: "var(--fg-tertiary)", letterSpacing: "0.1em" }}
        >
          Chat
        </span>
        <span className="text-[11px]" style={{ color: "var(--muted)" }}>
          三阶段流水线 · 草稿 → 精修 → 评估
        </span>
        <div
          className="inline-flex items-center gap-[4px] text-[9px] font-medium uppercase mt-0.5 py-0.5"
          style={{ letterSpacing: "0.06em" }}
        >
          <PipelineStep label="Draft" status={isBusy ? "done" : "idle"} />
          <span className="chat-pipeline-arrow">&rarr;</span>
          <PipelineStep label="Refine" status={isBusy ? "active" : "idle"} />
          <span className="chat-pipeline-arrow">&rarr;</span>
          <PipelineStep label="Evaluate" status="idle" />
        </div>
      </div>

      {/* API not configured warning */}
      {loaded && !isConfigured && (
        <div
          className="px-sp-4 py-sp-2 text-xs border-b flex items-center gap-sp-2"
          style={{
            color: "var(--warn)",
            background: "oklch(0.74 0.10 85 / 0.06)",
            borderColor: "oklch(0.74 0.10 85 / 0.12)",
          }}
        >
          <svg className="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          请先点击右上角齿轮配置 API Key
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-sp-5 flex flex-col gap-sp-4 min-h-0">
        {/* Empty state */}
        {messages.length === 0 && (
          <div
            className="flex-1 flex flex-col items-center justify-center text-center gap-sp-4"
            style={{ color: "var(--muted)" }}
          >
            <svg
              className="w-12 h-12"
              style={{ color: "var(--border)" }}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
            <p className="text-[13px] leading-relaxed max-w-[240px]">
              发送一条消息开始，后端会跑完三阶段流水线后流式输出结果。
            </p>
          </div>
        )}

        {messages.map((m, i) => {
          const isAssistant = m.role === "assistant";
          const text = collectMessageText(m.parts);
          const showInsert = isAssistant && onInsertIntoEditor && text.length > 0 && status !== "streaming";

          return (
            <div
              key={m.id}
              className="flex flex-col max-w-[88%]"
              style={{
                alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                animation: `fadeInUp 0.35s var(--ease-out) ${i * 60}ms both`,
              }}
            >
              <div
                className="px-sp-4 py-sp-3 text-[13px] leading-[1.65] transition-all"
                style={{
                  background: m.role === "user" ? "var(--accent)" : "var(--surface)",
                  color: m.role === "user" ? "var(--bg)" : "var(--fg-secondary)",
                  borderRadius: m.role === "user"
                    ? "var(--radius-md) var(--radius-md) var(--radius-sm) var(--radius-md)"
                    : "var(--radius-md) var(--radius-md) var(--radius-md) var(--radius-sm)",
                  border: m.role === "user" ? "none" : "1px solid var(--border-subtle)",
                  fontWeight: m.role === "user" ? 500 : 400,
                }}
                onMouseEnter={(e) => {
                  if (isAssistant) {
                    e.currentTarget.style.boxShadow = "var(--shadow-sm)";
                    e.currentTarget.style.transform = "translateY(-1px)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (isAssistant) {
                    e.currentTarget.style.boxShadow = "none";
                    e.currentTarget.style.transform = "translateY(0)";
                  }
                }}
              >
                {m.parts.map((part, j) =>
                  part.type === "text" ? (
                    <span key={j} className="whitespace-pre-wrap">{part.text}</span>
                  ) : null,
                )}
              </div>
              {showInsert && (
                <div className="mt-sp-2 self-end">
                  <button
                    type="button"
                    onClick={() => onInsertIntoEditor?.(text)}
                    className="text-[11px] font-medium px-3 py-1 rounded-sm border transition-colors"
                    style={{
                      borderColor: "var(--accent-muted)",
                      color: "var(--accent)",
                      letterSpacing: "0.02em",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = "var(--accent-bg)";
                      e.currentTarget.style.borderColor = "var(--accent)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "transparent";
                      e.currentTarget.style.borderColor = "var(--accent-muted)";
                    }}
                  >
                    插入到编辑器
                  </button>
                </div>
              )}
            </div>
          );
        })}

        {/* Typing indicator */}
        {isBusy && (
          <div className="text-[12px] px-sp-4 py-sp-2 flex items-center gap-sp-2" style={{ color: "var(--muted)" }}>
            <div className="flex gap-[3px]">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="w-[3px] h-[3px] rounded-full"
                  style={{
                    background: "var(--accent-muted)",
                    animation: `typing 1.4s infinite ${i * 0.2}s`,
                  }}
                />
              ))}
            </div>
            Pipeline running…
          </div>
        )}

        {/* Error banner */}
        {error && (
          <div
            className="flex items-start gap-sp-3 p-sp-4 rounded-md text-xs mx-sp-4"
            style={{
              background: "oklch(0.60 0.16 25 / 0.08)",
              border: "1px solid oklch(0.60 0.16 25 / 0.15)",
              color: "var(--danger)",
            }}
          >
            <svg className="w-4 h-4 shrink-0 mt-px" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span className="flex-1">{errorMessage}</span>
          </div>
        )}
      </div>

      {/* PerfPulse: last-generation stage timings */}
      {lastPerf && !isBusy && (
        <div
          className="px-sp-5 py-sp-2 border-t flex flex-wrap items-center gap-x-sp-3 gap-y-1 shrink-0"
          style={{
            background: "var(--surface)",
            borderColor: "var(--border-subtle)",
          }}
        >
          <span
            className="text-[9px] font-semibold uppercase tracking-wider"
            style={{ color: "var(--fg-tertiary)" }}
          >
            耗时
          </span>
          <PerfChip label="检索" ms={lastPerf.retrieval_ms} />
          <PerfChip label="草稿" ms={lastPerf.draft_ms} />
          <PerfChip label="精修" ms={lastPerf.refine_ms} />
          <PerfChip label="评估" ms={lastPerf.evaluate_ms} />
          <PerfChip label="安全" ms={lastPerf.safety_ms} />
        </div>
      )}

      {/* Chat input */}
      <form
        onSubmit={onSubmit}
        className="px-sp-4 py-sp-3 border-t shrink-0"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
        }}
      >
        <div className="flex gap-sp-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={loaded && !isConfigured ? "请先配置 API Key 后再发送…" : "输入要写的内容…"}
            disabled={isBusy || (loaded && !isConfigured)}
            className="flex-1 px-sp-4 py-sp-3 border rounded-md text-[13px] outline-none resize-none min-h-[40px] max-h-[120px] transition-all disabled:opacity-50"
            style={{
              background: "var(--bg)",
              borderColor: "var(--border)",
              color: "var(--fg)",
              lineHeight: "1.5",
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = "var(--accent-muted)";
              e.currentTarget.style.boxShadow = "0 0 0 2px var(--accent-glow)";
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = "var(--border)";
              e.currentTarget.style.boxShadow = "none";
            }}
            rows={1}
          />
          {isBusy ? (
            <button
              type="button"
              onClick={stop}
              className="w-10 h-10 flex items-center justify-center rounded-md shrink-0 transition-colors"
              style={{ background: "var(--danger)", color: "white" }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <rect x="4" y="4" width="16" height="16" rx="2" />
              </svg>
            </button>
          ) : (
            <button
              type="submit"
              disabled={sendDisabled}
              className="w-10 h-10 flex items-center justify-center rounded-md shrink-0 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
              style={{ background: "var(--accent)", color: "var(--bg)" }}
              onMouseEnter={(e) => {
                if (!sendDisabled) {
                  e.currentTarget.style.background = "var(--accent-hover)";
                  e.currentTarget.style.transform = "translateY(-1px)";
                  e.currentTarget.style.boxShadow = "var(--shadow-glow)";
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "var(--accent)";
                e.currentTarget.style.transform = "translateY(0)";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

function PerfChip({ label, ms }: { label: string; ms: number | undefined }) {
  if (typeof ms !== "number") return null;
  return (
    <span
      className="text-[10px] font-mono inline-flex items-center gap-1"
      style={{
        color: ms > 2000 ? "var(--warn)" : "var(--muted)",
      }}
      title={`${label} 阶段耗时`}
    >
      <span style={{ color: "var(--fg-tertiary)" }}>{label}</span>
      {ms >= 100 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`}
    </span>
  );
}

function PipelineStep({ label, status }: { label: string; status: "idle" | "done" | "active" }) {
  const className = `chat-pipeline-step${status === "done" ? " chat-pipeline-step--done" : status === "active" ? " chat-pipeline-step--active" : ""}`;
  return (
    <span className={className}>
      <span className="chat-pipeline-step__dot" />
      <span className="chat-pipeline-step__label">{label}</span>
    </span>
  );
}
