"use client";

/**
 * 创作向导 (CreationWizard) — R5-1
 *
 * 把「题材 → 大纲 → 分章 → 正文」五步手动操作收成一个引导式流程：
 *   1. 设定：书名 / 体裁 / 风格基调 / 故事简介 / 目标章数
 *   2. 大纲：一键流式生成（可手动编辑 / 粘贴自备大纲）
 *   3. 应用：创建作品 + 自动建章 + 自动提取角色/世界观/事件 → 直接进入编辑器
 *
 * 完全复用既有能力：useChat 流式（与 AIToolPanel 同构）、createDocument、
 * createChapter、extractEntitiesFromOutline 等，不新增后端接口。
 */
import { DefaultChatTransport } from "ai";
import { useChat } from "@ai-sdk/react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { useProviderConfig } from "@/hooks/use-provider-config";
import { chatEndpoint } from "@/lib/config";
import { loadProviderConfig, ownerAuthHeaders } from "@/lib/settings";
import { createDocument } from "@/lib/documents";
import { createChapter } from "@/lib/chapters";
import { extractEntitiesFromOutline } from "@/lib/extract-entities";
import { createCharacter } from "@/lib/characters";
import { createWorldSetting } from "@/lib/world-settings";
import { createPlotEvent } from "@/lib/plot-events";

const GENRE_OPTIONS = [
  "玄幻",
  "修仙",
  "都市",
  "历史",
  "科幻",
  "悬疑",
  "言情",
  "武侠",
  "末世",
  "系统",
  "其他",
];
const TONE_OPTIONS = [
  "热血爽文",
  "轻松治愈",
  "黑暗压抑",
  "烧脑悬疑",
  "甜宠",
  "虐心",
  "成长励志",
  "其他",
];
const STEPS = ["设定", "大纲", "应用"];

interface CreationWizardProps {
  open: boolean;
  onClose: () => void;
}

export function CreationWizard({ open, onClose }: CreationWizardProps) {
  const router = useRouter();
  const { isConfigured, loaded } = useProviderConfig();

  // ── Step 1 · 设定 ─────────────────────────────────────────────────
  const [title, setTitle] = useState("");
  const [genre, setGenre] = useState("玄幻");
  const [tone, setTone] = useState("热血爽文");
  const [description, setDescription] = useState("");
  const [targetChapters, setTargetChapters] = useState("");

  // ── Step 2 · 大纲 ─────────────────────────────────────────────────
  const [step, setStep] = useState(1);
  const [outlineDraft, setOutlineDraft] = useState("");
  const [generateError, setGenerateError] = useState<string | null>(null);

  // ── Step 3 · 应用 ─────────────────────────────────────────────────
  const [applying, setApplying] = useState(false);
  const [applyStatus, setApplyStatus] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Stream transport — 与 AIToolPanel 同构（BYOK + 本地密钥）。
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

  const { messages, sendMessage, status, error: chatError } = useChat({
    transport,
  });
  const isGenerating = status === "submitted" || status === "streaming";

  // 最新助手文本（流式逐字）。
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

  // 生成结束 → 把结果落入可编辑草稿。
  const wasGenerating = useRef(false);
  useEffect(() => {
    if (wasGenerating.current && !isGenerating) {
      if (chatError) {
        setGenerateError(chatError instanceof Error ? chatError.message : "生成失败");
      } else if (latestAssistantText.trim()) {
        setOutlineDraft(latestAssistantText);
        setGenerateError(null);
      }
    }
    wasGenerating.current = isGenerating;
  }, [isGenerating, latestAssistantText, chatError]);

  // 打开时重置。
  useEffect(() => {
    if (open) {
      setStep(1);
      setError(null);
      setGenerateError(null);
      setOutlineDraft("");
      setApplyStatus("");
      setApplying(false);
    }
  }, [open]);

  if (!open) return null;

  const buildOutlinePrompt = (): string => {
    const genrePart = genre ? `体裁：${genre}\n` : "";
    const tonePart = tone ? `风格基调：${tone}\n` : "";
    const descPart = description.trim() ? `故事简介：${description.trim()}\n` : "";
    const chapPart = targetChapters.trim()
      ? `目标章数：${targetChapters.trim()}章\n`
      : "";
    return `[task:outline] ${genrePart}${tonePart}${descPart}${chapPart}请为这本小说生成完整的故事大纲，包含主题、核心冲突、主要角色、世界观设定、每章梗概。`;
  };

  const handleGenerate = () => {
    setGenerateError(null);
    sendMessage({ text: buildOutlinePrompt() });
  };

  // 解析大纲标题行 → 批量建章（与编辑器「应用大纲」同一套规则）。
  const applyOutlineToChapters = async (docId: number, outlineText: string) => {
    const lines = outlineText.split("\n");
    const entries: Array<{ idx: number; title: string }> = [];
    for (let i = 0; i < lines.length; i++) {
      const trimmed = lines[i].trim();
      if (/^\d+[\.\、]/.test(trimmed) || /^第[一二三四五六七八九十百千\d]+章/.test(trimmed)) {
        const t =
          trimmed.replace(/^\d+[\.\、]\s*/, "").trim().slice(0, 50) ||
          `第${entries.length + 1}章`;
        entries.push({ idx: i, title: t });
      }
    }
    for (let i = 0; i < entries.length; i++) {
      const start = entries[i].idx + 1;
      const end = i + 1 < entries.length ? entries[i + 1].idx : lines.length;
      const summaryLines = lines.slice(start, end).filter((l) => l.trim());
      const summary = summaryLines.join("\n").trim().slice(0, 500);
      await createChapter(docId, {
        chapter_index: i,
        title: entries[i].title,
        ...(summary ? { summary } : {}),
      });
    }
  };

  const handleApply = async () => {
    const outlineText = outlineDraft.trim();
    if (!title.trim() || !outlineText) return;
    setApplying(true);
    setApplyStatus("正在创建作品…");
    setError(null);
    try {
      const doc = await createDocument({
        title: title.trim(),
        content_html: "",
        content_text: "",
        doc_type: "novel",
        category: "长篇",
        metadata_json: {
          genre,
          tone,
          description: description.trim(),
          outline: outlineText,
          outline_updated_at: new Date().toISOString(),
          writing_type: "长篇",
          pov: "第三人称",
        },
      });

      setApplyStatus("正在建立章节…");
      await applyOutlineToChapters(doc.id, outlineText);

      setApplyStatus("正在提取设定…");
      try {
        const entities = await extractEntitiesFromOutline(outlineText);
        await Promise.all([
          Promise.allSettled(
            entities.characters.map((c) =>
              createCharacter(doc.id, {
                name: c.name,
                role: c.role || "其他",
                description: c.description || "",
                arc_summary: c.arc_summary || "",
              }),
            ),
          ),
          Promise.allSettled(
            entities.world_settings.map((w) =>
              createWorldSetting(doc.id, {
                category: w.category || "其他",
                title: w.title,
                content_text: w.content_text || "",
              }),
            ),
          ),
          Promise.allSettled(
            entities.plot_events.map((p) =>
              createPlotEvent(doc.id, {
                summary: p.summary,
                event_type: p.event_type || "其他",
                chapter_index: p.chapter_index ?? null,
              }),
            ),
          ),
        ]);
      } catch {
        // 设定提取失败不阻塞进入编辑器（可稍后在编辑器手动 AI 提取）。
      }

      router.push(`/novels/${doc.id}/editor`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
      setApplying(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-sp-6"
      style={{ background: "rgba(0,0,0,0.55)" }}
      onClick={applying ? undefined : onClose}
    >
      <div
        className="w-full max-w-[560px] max-h-[85vh] flex flex-col rounded-lg border shadow-2xl"
        style={{ background: "var(--surface)", borderColor: "var(--border-hairline)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="px-sp-5 py-sp-4 border-b flex items-center gap-sp-3 shrink-0"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <span className="text-[15px] font-semibold" style={{ color: "var(--fg)" }}>
            ✨ 创作向导
          </span>
          <span className="text-[11px]" style={{ color: "var(--muted)" }}>
            从灵感三步到开写
          </span>
          <span className="flex-1" />
          {!applying && (
            <button
              type="button"
              onClick={onClose}
              className="w-7 h-7 flex items-center justify-center rounded-sm transition-colors"
              style={{ color: "var(--muted)" }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "var(--surface-2)";
                e.currentTarget.style.color = "var(--fg)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
                e.currentTarget.style.color = "var(--muted)";
              }}
              title="关闭"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>

        {/* Step indicator */}
        <div
          className="px-sp-5 py-sp-3 border-b flex items-center gap-sp-2 shrink-0"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          {STEPS.map((label, i) => {
            const n = i + 1;
            const active = n === step;
            const done = n < step;
            return (
              <div key={label} className="flex items-center gap-sp-2">
                <div
                  className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold transition-colors"
                  style={{
                    background: active
                      ? "var(--accent)"
                      : done
                        ? "var(--accent-bg)"
                        : "var(--surface-2)",
                    color: active ? "var(--bg)" : done ? "var(--accent)" : "var(--muted)",
                  }}
                >
                  {done ? "✓" : n}
                </div>
                <span
                  className="text-[11px] font-medium"
                  style={{ color: active ? "var(--fg)" : "var(--muted)" }}
                >
                  {label}
                </span>
                {n < STEPS.length && (
                  <span className="w-6 h-px mx-sp-1" style={{ background: "var(--border-subtle)" }} />
                )}
              </div>
            );
          })}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-sp-5 py-sp-4 min-h-0">
          {step === 1 && (
            <div className="space-y-sp-3">
              <Field label="书名">
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="给作品起个名字"
                  className="w-full px-sp-3 py-sp-2 rounded-sm text-[13px] bg-transparent border outline-none"
                  style={{ borderColor: "var(--border)", color: "var(--fg)" }}
                />
              </Field>
              <div className="grid grid-cols-2 gap-sp-3">
                <Field label="体裁">
                  <select
                    value={genre}
                    onChange={(e) => setGenre(e.target.value)}
                    className="w-full px-sp-2 py-sp-2 rounded-sm text-[13px] bg-transparent border outline-none"
                    style={{ borderColor: "var(--border)", color: "var(--fg)" }}
                  >
                    {GENRE_OPTIONS.map((g) => (
                      <option key={g} value={g}>
                        {g}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="风格基调">
                  <select
                    value={tone}
                    onChange={(e) => setTone(e.target.value)}
                    className="w-full px-sp-2 py-sp-2 rounded-sm text-[13px] bg-transparent border outline-none"
                    style={{ borderColor: "var(--border)", color: "var(--fg)" }}
                  >
                    {TONE_OPTIONS.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <Field label="故事简介（可选）">
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="一句话讲清：主角是谁，要做什么，遇到什么阻碍…"
                  rows={3}
                  className="w-full px-sp-3 py-sp-2 rounded-sm text-[13px] leading-[1.7] bg-transparent border outline-none resize-y"
                  style={{ borderColor: "var(--border)", color: "var(--fg)" }}
                />
              </Field>
              <Field label="目标章数（可选）">
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={targetChapters}
                  onChange={(e) => setTargetChapters(e.target.value)}
                  placeholder="如 50"
                  className="w-full px-sp-3 py-sp-2 rounded-sm text-[13px] bg-transparent border outline-none"
                  style={{ borderColor: "var(--border)", color: "var(--fg)" }}
                />
              </Field>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-sp-3">
              <div
                className="px-sp-3 py-sp-2.5 rounded-sm text-[12px] leading-[1.6]"
                style={{ background: "var(--accent-bg)", color: "var(--fg-secondary)" }}
              >
                {isConfigured || !loaded
                  ? "点击「生成大纲」由 AI 起草；也可直接在下框粘贴或手写大纲，然后进入下一步。"
                  : "未检测到模型配置：可先手动填写大纲，或打开设置配置 API Key 后回来生成。"}
              </div>
              <textarea
                value={outlineDraft}
                onChange={(e) => setOutlineDraft(e.target.value)}
                rows={14}
                placeholder={"生成或粘贴大纲…\n\n例如：\n1. 第一章 张三入宗\n   张三在青云宗拜入门下，开启修仙之路。\n2. 第二章 修炼突破\n   张三苦修三个月，终于突破练气期。"}
                className="w-full px-sp-3 py-sp-2 rounded-sm text-[12px] leading-[1.7] bg-transparent border outline-none resize-y"
                style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
              />
              {generateError && (
                <p className="text-[12px]" style={{ color: "var(--danger)" }}>
                  {generateError}
                </p>
              )}
              <div className="flex items-center gap-sp-2">
                <button
                  type="button"
                  onClick={handleGenerate}
                  disabled={isGenerating || !title.trim()}
                  className="px-sp-3 py-sp-1.5 rounded-sm text-[12px] font-medium transition-colors disabled:opacity-40"
                  style={{
                    background: "var(--accent)",
                    color: "var(--bg)",
                  }}
                >
                  {isGenerating ? "生成中…" : "生成大纲"}
                </button>
                {outlineDraft.trim() && (
                  <button
                    type="button"
                    onClick={handleGenerate}
                    disabled={isGenerating}
                    className="px-sp-3 py-sp-1.5 rounded-sm text-[12px] font-medium transition-colors"
                    style={{
                      border: "1px solid var(--border)",
                      color: "var(--fg-secondary)",
                    }}
                  >
                    重新生成
                  </button>
                )}
                {isGenerating && (
                  <span className="text-[12px] tabular-nums" style={{ color: "var(--muted)" }}>
                    流式生成中…
                  </span>
                )}
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-sp-3">
              <div
                className="px-sp-4 py-sp-3 rounded-sm border"
                style={{ borderColor: "var(--border-subtle)", background: "var(--bg)" }}
              >
                <p className="text-[13px] font-semibold mb-sp-2" style={{ color: "var(--fg)" }}>
                  {title.trim() || "未命名作品"}
                </p>
                <p className="text-[12px] leading-[1.7] whitespace-pre-wrap max-h-[140px] overflow-y-auto" style={{ color: "var(--fg-secondary)" }}>
                  {outlineDraft}
                </p>
              </div>
              <p className="text-[12px]" style={{ color: "var(--muted)" }}>
                点击后：创建作品 → 按大纲自动建立章节 → 提取角色/世界观/事件 → 直接进入编辑器开写。
              </p>
              {applyStatus && (
                <p className="text-[12px]" style={{ color: "var(--accent)" }}>
                  {applyStatus}
                </p>
              )}
              {error && (
                <p className="text-[12px]" style={{ color: "var(--danger)" }}>
                  {error}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          className="px-sp-5 py-sp-3.5 border-t flex items-center gap-sp-2 shrink-0"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <span className="flex-1" />
          {step > 1 && !applying && (
            <button
              type="button"
              onClick={() => {
                setStep((s) => s - 1);
                setError(null);
              }}
              className="px-sp-4 py-sp-2 rounded-sm text-[12px] font-medium transition-colors"
              style={{ border: "1px solid var(--border)", color: "var(--fg-secondary)" }}
            >
              上一步
            </button>
          )}
          {step < 3 && (
            <button
              type="button"
              disabled={step === 1 ? !title.trim() : !outlineDraft.trim()}
              onClick={() => {
                setStep((s) => s + 1);
                setError(null);
              }}
              className="px-sp-4 py-sp-2 rounded-sm text-[12px] font-semibold transition-colors disabled:opacity-40"
              style={{ background: "var(--accent)", color: "var(--bg)" }}
            >
              {step === 1 ? "下一步：生成大纲" : "下一步：确认"}
            </button>
          )}
          {step === 3 && (
            <button
              type="button"
              onClick={() => void handleApply()}
              disabled={applying}
              className="px-sp-4 py-sp-2 rounded-sm text-[12px] font-semibold transition-colors disabled:opacity-40"
              style={{ background: "var(--accent)", color: "var(--bg)" }}
            >
              {applying ? "创建中…" : "创建作品并开始创作"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span
        className="block text-[11px] font-medium mb-sp-1"
        style={{ color: "var(--muted)" }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}
