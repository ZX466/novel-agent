"use client";

import { DefaultChatTransport } from "ai";
import { useChat } from "@ai-sdk/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { chatEndpoint } from "@/lib/config";
import { loadProviderConfig, ownerAuthHeaders } from "@/lib/settings";
import { createWorldSetting } from "@/lib/world-settings";
import { createCharacter } from "@/lib/characters";
import { getDocument, updateDocument } from "@/lib/documents";
import { parseCreativeKit, type CreativeKitPackage } from "@/lib/creative-kit";

interface CreativeKitDialogProps {
  docId: number;
  open: boolean;
  onClose: () => void;
  onApplied?: () => void;
}

const GENRES = ["玄幻", "修仙", "都市", "历史", "科幻", "悬疑", "言情", "武侠", "末世", "系统", "其他"];
const TONES = ["热血爽文", "轻松治愈", "黑暗压抑", "烧脑悬疑", "甜宠", "虐心", "成长励志", "其他"];

function buildKitPrompt(genre: string, tone: string, keywords: string): string {
  const kw = keywords.trim() ? `，题材关键词：${keywords.trim()}` : "";
  return (
    `[task:generate] 你是资深小说设定师。请为一部「${genre} · ${tone}」小说${kw}生成一套创作灵感套件，` +
    "包含世界观（3-5 条）、主要人物（3-5 个）和主线大纲。只输出一个 JSON 对象，不要任何其他文字，格式：\n" +
    '{"world_settings":[{"title":"条目名","category":"地理/势力/文化/力量体系/历史/其他","content_text":"设定内容"}],' +
    '"characters":[{"name":"角色名","role":"主角/配角/反派/其他","description":"人设","attributes":{"性格":"…"},"arc_summary":"成长弧线"}],' +
    '"outline":"用编号列表描述整部主线大纲"}'
  );
}

export function CreativeKitDialog({
  docId,
  open,
  onClose,
  onApplied,
}: CreativeKitDialogProps) {
  const [genre, setGenre] = useState("玄幻");
  const [tone, setTone] = useState("热血爽文");
  const [keywords, setKeywords] = useState("");
  const [kit, setKit] = useState<CreativeKitPackage | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyStatus, setApplyStatus] = useState("");

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

  const { messages, sendMessage, status } = useChat({ transport });
  const isGenerating = status === "submitted" || status === "streaming";

  const latestText = useMemo(() => {
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

  // Generation finished -> parse into a structured kit for review.
  const wasGenerating = useRef(false);
  useEffect(() => {
    if (wasGenerating.current && !isGenerating && latestText.trim()) {
      setKit(parseCreativeKit(latestText));
    }
    wasGenerating.current = isGenerating;
  }, [isGenerating, latestText]);

  if (!open) return null;

  const handleGenerate = () => {
    setKit(null);
    setApplyStatus("");
    void sendMessage({ text: buildKitPrompt(genre, tone, keywords) });
  };

  const handleApply = async () => {
    if (!kit) return;
    setApplying(true);
    setApplyStatus("");
    try {
      for (const ws of kit.world_settings) {
        await createWorldSetting(docId, {
          title: ws.title,
          category: ws.category,
          content_text: ws.content_text,
        });
      }
      for (const ch of kit.characters) {
        await createCharacter(docId, {
          name: ch.name,
          role: ch.role,
          description: ch.description,
          attributes: ch.attributes,
          arc_summary: ch.arc_summary,
        });
      }
      if (kit.outline.trim()) {
        const doc = await getDocument(docId);
        const meta = { ...(doc.metadata_json ?? {}), outline: kit.outline };
        await updateDocument(docId, { metadata_json: meta });
      }
      setApplyStatus(
        `已应用：世界观 ${kit.world_settings.length} 条 · 人物 ${kit.characters.length} 个 · 主线大纲`,
      );
      onApplied?.();
    } catch (err) {
      setApplyStatus(
        `应用失败：${err instanceof Error ? err.message : "未知错误"}`,
      );
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0" style={{ background: "rgba(0,0,0,0.4)" }} onClick={onClose} />
      <div
        className="relative z-10 w-[720px] max-w-[92vw] max-h-[86vh] flex flex-col rounded-lg border shadow-2xl"
        style={{ background: "var(--surface)", borderColor: "var(--border-hairline)" }}
      >
        {/* Header */}
        <div className="flex items-center px-sp-5 py-sp-3 border-b shrink-0" style={{ borderColor: "var(--border-subtle)" }}>
          <span className="text-[13px] font-semibold" style={{ color: "var(--fg)" }}>
            ✨ 灵感套件
          </span>
          <span className="flex-1" />
          <button type="button" onClick={onClose} className="text-[12px] px-sp-2 py-px rounded-sm" style={{ color: "var(--muted)" }} aria-label="关闭">
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-sp-5 py-sp-4 space-y-sp-4">
          {/* Input form */}
          <div className="space-y-sp-3">
            <div className="flex gap-sp-3">
              <label className="flex-1">
                <span className="text-[10px] uppercase" style={{ color: "var(--fg-tertiary)" }}>题材</span>
                <select
                  value={genre}
                  onChange={(e) => setGenre(e.target.value)}
                  className="w-full mt-1 px-sp-2 py-sp-1.5 rounded-sm border text-[12px] bg-transparent"
                  style={{ borderColor: "var(--border)", color: "var(--fg)" }}
                >
                  {GENRES.map((g) => <option key={g} value={g}>{g}</option>)}
                </select>
              </label>
              <label className="flex-1">
                <span className="text-[10px] uppercase" style={{ color: "var(--fg-tertiary)" }}>风格</span>
                <select
                  value={tone}
                  onChange={(e) => setTone(e.target.value)}
                  className="w-full mt-1 px-sp-2 py-sp-1.5 rounded-sm border text-[12px] bg-transparent"
                  style={{ borderColor: "var(--border)", color: "var(--fg)" }}
                >
                  {TONES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
            </div>
            <label className="block">
              <span className="text-[10px] uppercase" style={{ color: "var(--fg-tertiary)" }}>关键词（可选）</span>
              <input
                type="text"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                placeholder="如：金手指、宗门、炼丹"
                className="w-full mt-1 px-sp-2 py-sp-1.5 rounded-sm border text-[12px] bg-transparent"
                style={{ borderColor: "var(--border)", color: "var(--fg)" }}
              />
            </label>
            <button
              type="button"
              onClick={handleGenerate}
              disabled={isGenerating}
              className="px-sp-4 py-sp-2 rounded-sm text-[12px] font-medium border transition-colors disabled:opacity-50"
              style={{
                borderColor: "var(--accent)",
                color: "var(--accent)",
                background: isGenerating ? "var(--surface-2)" : "transparent",
              }}
            >
              {isGenerating ? "生成中…" : "一键生成设定包"}
            </button>
          </div>

          {/* Streaming / parsed preview */}
          {isGenerating && (
            <div className="text-[12px] whitespace-pre-wrap" style={{ color: "var(--fg-secondary)" }}>
              {latestText}
            </div>
          )}

          {!isGenerating && kit && (
            <div className="space-y-sp-3">
              <div className="text-[12px] font-medium" style={{ color: "var(--fg)" }}>
                生成结果（可检查后应用）
              </div>
              {kit.world_settings.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase mb-sp-1" style={{ color: "var(--fg-tertiary)" }}>世界观 · {kit.world_settings.length}</div>
                  <div className="space-y-sp-1">
                    {kit.world_settings.map((w, i) => (
                      <div key={i} className="text-[12px] px-sp-3 py-sp-2 rounded-sm" style={{ background: "var(--surface-2)", color: "var(--fg-secondary)" }}>
                        <span className="font-medium" style={{ color: "var(--fg)" }}>{w.title}</span>
                        {w.category ? <span className="ml-sp-2 text-[10px]" style={{ color: "var(--muted)" }}>[{w.category}]</span> : null}
                        <div className="mt-px">{w.content_text}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {kit.characters.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase mb-sp-1" style={{ color: "var(--fg-tertiary)" }}>人物 · {kit.characters.length}</div>
                  <div className="space-y-sp-1">
                    {kit.characters.map((c, i) => (
                      <div key={i} className="text-[12px] px-sp-3 py-sp-2 rounded-sm" style={{ background: "var(--surface-2)", color: "var(--fg-secondary)" }}>
                        <span className="font-medium" style={{ color: "var(--fg)" }}>{c.name}</span>
                        {c.role ? <span className="ml-sp-2 text-[10px]" style={{ color: "var(--muted)" }}>[{c.role}]</span> : null}
                        {c.description ? <div className="mt-px">{c.description}</div> : null}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {kit.outline && (
                <div>
                  <div className="text-[10px] uppercase mb-sp-1" style={{ color: "var(--fg-tertiary)" }}>主线大纲</div>
                  <div className="text-[12px] px-sp-3 py-sp-2 rounded-sm whitespace-pre-wrap" style={{ background: "var(--surface-2)", color: "var(--fg-secondary)" }}>
                    {kit.outline}
                  </div>
                </div>
              )}
              {kit.world_settings.length === 0 && kit.characters.length === 0 && !kit.outline && (
                <div className="text-[12px]" style={{ color: "var(--danger)" }}>未能解析出结构化设定，请重新生成或检查输出格式。</div>
              )}
            </div>
          )}

          {applyStatus && (
            <div className="text-[12px]" style={{ color: applyStatus.startsWith("应用失败") ? "var(--danger)" : "var(--accent)" }}>
              {applyStatus}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-sp-2 px-sp-5 py-sp-3 border-t shrink-0" style={{ borderColor: "var(--border-subtle)" }}>
          <button type="button" onClick={onClose} className="px-sp-3 py-sp-1.5 rounded-sm text-[12px]" style={{ color: "var(--muted)" }}>
            关闭
          </button>
          <button
            type="button"
            onClick={() => void handleApply()}
            disabled={!kit || applying || isGenerating}
            className="px-sp-4 py-sp-1.5 rounded-sm text-[12px] font-medium border transition-colors disabled:opacity-40"
            style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
          >
            {applying ? "应用中…" : "应用到作品"}
          </button>
        </div>
      </div>
    </div>
  );
}
