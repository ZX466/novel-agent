"use client";

import { PerfChatTransport } from "@/lib/perf-transport";
import { useChat } from "@ai-sdk/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { chatEndpoint } from "@/lib/config";
import { loadProviderConfig, ownerAuthHeaders } from "@/lib/settings";
import { listCharacters } from "@/lib/characters";
import { getDocument } from "@/lib/documents";
import { listWorldSettings } from "@/lib/world-settings";
import {
  applyCreativeKit,
  parseCreativeKit,
  type CreativeKitPackage,
} from "@/lib/creative-kit";
import type { EditorDoc } from "@/lib/types";

interface CreativeKitDialogProps {
  docId: number;
  open: boolean;
  onClose: () => void;
  /** Called after a successful apply; receives the freshly-updated document so
   *  the parent can refresh its own copy (prevents stale-metadata overwrites). */
  onApplied?: (updatedDoc: EditorDoc) => void;
}

const GENRES = ["玄幻", "修仙", "都市", "历史", "科幻", "悬疑", "言情", "武侠", "末世", "系统", "其他"];
const TONES = ["热血爽文", "轻松治愈", "黑暗压抑", "烧脑悬疑", "甜宠", "虐心", "成长励志", "其他"];

/**
 * R10-⑦: kit prompt v2 — 唯一主角约束、6-10 张多样化角色卡、关系网输出、
 * 库内已有人物名注入（生成时避开重复）。`existingNames` = 当前作品已有
 * 人物（空数组 = 新作品）。
 *
 * 作品上下文注入：`context` 携带当前作品现状（标题/简介/已有角色定位/
 * 世界观标题/现有大纲），生成结果锚定既有故事而非凭空编造。空值字段
 * 省略，全部为空时不输出「作品现状」块（等价旧行为）。
 */
interface KitContext {
  title: string;
  description: string;
  outline: string;
  castSummaries: string[];
  worldTitles: string[];
}

function buildKitPrompt(
  genre: string,
  tone: string,
  keywords: string,
  existingNames: string[],
  context: KitContext,
): string {
  const kw = keywords.trim() ? `，题材关键词：${keywords.trim()}` : "";
  const avoid = existingNames.length
    ? `\n以下人物已存在于作品中，严禁再生成同名或明显同人的角色：${existingNames.join("、")}。新角色必须与他们互补（如导师、宿敌、盟友、竞争者），不要重复已有定位。`
    : "";
  const contextLines = [
    context.title.trim() ? `标题：${context.title.trim()}` : "",
    context.description.trim() ? `简介：${context.description.trim()}` : "",
    context.castSummaries.length ? `已有角色：${context.castSummaries.join("；")}` : "",
    context.worldTitles.length ? `已有世界观：${context.worldTitles.join("、")}` : "",
    context.outline.trim() ? `现有大纲：${context.outline.trim().slice(0, 3000)}` : "",
  ].filter(Boolean);
  const contextBlock = contextLines.length
    ? `\n\n【作品现状】\n${contextLines.join("\n")}\n`
    : "";
  const anchor =
    contextLines.length
      ? `请基于作品现状生成与当前故事一致、延续既有设定的灵感套件，世界观与人物不得与已有设定冲突，大纲作为主线参考可扩写但不得推翻既有走向。`
      : "请生成一套创作灵感套件。";
  return (
    `[task:generate] 你是资深小说设定师。请为一部「${genre} · ${tone}」小说${kw}${anchor}` +
    `${contextBlock}` +
    "包含世界观（3-5 条）、人物（6-10 个）和主线大纲。\n" +
    "人物要求：\n" +
    "- 「主角」恰好 1 名（全书唯一核心，不设双主角）\n" +
    "- 其余为配角/反派/导师/其他，卡型尽量多样：宿敌、导师、挚友、红颜/蓝颜、家族长辈、神秘人等\n" +
    "- 每个角色写清 name/role/description（含性格+动机）/attributes/arc_summary\n" +
    "- 另生成 relationships 人物关系网（6-12 条），覆盖主角与主要角色的联结" + avoid + "\n" +
    "只输出一个 JSON 对象，不要任何其他文字，格式：\n" +
    '{"world_settings":[{"title":"条目名","category":"地理/势力/文化/力量体系/历史/其他","content_text":"设定内容"}],' +
    '"characters":[{"name":"角色名","role":"主角/配角/反派/导师/其他","description":"人设","attributes":{"性格":"…"},"arc_summary":"成长弧线"}],' +
    '"relationships":[{"subject":"角色A","object":"角色B","relation_type":"宿敌/师徒/挚友/亲属/暗恋等","strength":1-5}],' +
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

  // PerfChatTransport: 后端 SSE 含 data-stage/data-perf 自定义事件，
  // 自解析 transport 不经 AI SDK v5 严格 chunk 校验（裸未知 type 会炸流）。
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
        onPerf: () => {},
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

  // Modal focus semantics: initial focus into the dialog, keydown handling
  // (Escape close + Tab focus trap), and focus RETURN to the trigger on close.
  const dialogRef = useRef<HTMLDivElement>(null);
  const lastActiveRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (open) {
      lastActiveRef.current = document.activeElement as HTMLElement | null;
      dialogRef.current?.focus();
    } else if (lastActiveRef.current) {
      lastActiveRef.current.focus();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const node = dialogRef.current;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab" || !node) return;
      // Focus trap: keep Tab/Shift+Tab cycling within the dialog's focusables.
      const focusables = Array.from(
        node.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("disabled"));
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (!active || !node.contains(active)) {
        e.preventDefault();
        first.focus();
        return;
      }
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const handleGenerate = () => {
    setKit(null);
    setApplyStatus("");
    // 并行拉取作品现状（文档/角色/世界观）；单项失败降级为空，绝不阻塞生成。
    void Promise.all([
      getDocument(docId)
        .then((doc) => {
          const meta = (doc.metadata_json ?? {}) as Record<string, unknown>;
          return {
            title: doc.title ?? "",
            description:
              typeof meta.description === "string" ? meta.description : "",
            outline: typeof meta.outline === "string" ? meta.outline : "",
          };
        })
        .catch(() => ({ title: "", description: "", outline: "" })),
      listCharacters(docId, 500)
        .then((r) => ({
          names: r.items.map((c) => c.name),
          cast: r.items.map(
            (c) => `${c.name}（${c.role || "角色"}）`,
          ),
        }))
        .catch(() => ({ names: [] as string[], cast: [] as string[] })),
      listWorldSettings(docId, { limit: 100 })
        .then((r) => r.items.map((w) => w.title))
        .catch(() => [] as string[]),
    ]).then(([docCtx, chars, worldTitles]) => {
      // R10-⑦: inject the existing cast so the model avoids duplicates.
      sendMessage({
        text: buildKitPrompt(genre, tone, keywords, chars.names, {
          title: docCtx.title,
          description: docCtx.description,
          outline: docCtx.outline,
          castSummaries: chars.cast,
          worldTitles,
        }),
      });
    });
  };

  const handleApply = async () => {
    if (!kit) return;
    setApplying(true);
    setApplyStatus("");
    try {
      // Single atomic server-side apply: the backend locks the document row,
      // inserts world settings + characters (unique per title/name) + the
      // relationship web (resolved against existing + kit cast). The outline
      // is NEVER sent — the author's outline is their property; the kit's
      // generated outline is preview-only reference material.
      const res = await applyCreativeKit(docId, {
        world_settings: kit.world_settings.map((w) => ({
          title: w.title.slice(0, 200),
          category: w.category,
          content_text: w.content_text.slice(0, 20000),
        })),
        characters: kit.characters.map((c) => ({
          name: c.name.slice(0, 200),
          role: c.role,
          description: c.description?.slice(0, 20000),
          attributes:
            c.attributes &&
            typeof c.attributes === "object" &&
            !Array.isArray(c.attributes)
              ? c.attributes
              : undefined,
          arc_summary: c.arc_summary?.slice(0, 20000),
        })),
        relationships: kit.relationships,
      });
      const parts = [
        `世界观 ${res.created_world_settings}${res.skipped_world_settings ? `（跳过 ${res.skipped_world_settings}）` : ""}`,
        `人物 ${res.created_characters}${res.skipped_characters ? `（跳过 ${res.skipped_characters}）` : ""}`,
        res.created_relationships || res.skipped_relationships
          ? `关系 ${res.created_relationships}${res.skipped_relationships ? `（跳过 ${res.skipped_relationships}）` : ""}`
          : "",
      ].filter(Boolean);
      setApplyStatus(`已应用：${parts.join(" · ")}`);
      // Hand the freshest document back so the parent refreshes its copy —
      // never overwriting concurrent changes with a stale metadata_json later.
      onApplied?.(res.document);
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
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="灵感套件 Creative Kit"
        tabIndex={-1}
        className="relative z-10 w-[720px] max-w-[92vw] max-h-[86vh] flex flex-col rounded-lg border shadow-2xl outline-none"
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
              {kit.relationships.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase mb-sp-1" style={{ color: "var(--fg-tertiary)" }}>关系网 · {kit.relationships.length}</div>
                  <div className="flex flex-wrap gap-sp-1">
                    {kit.relationships.map((r, i) => (
                      <span
                        key={i}
                        className="text-[11px] px-sp-2 py-px rounded-full"
                        style={{ background: "var(--surface-2)", color: "var(--fg-secondary)", border: "1px solid var(--border-hairline)" }}
                      >
                        {r.subject} —{r.relation_type}— {r.object}
                        <span className="ml-1" style={{ color: "var(--accent)" }}>{r.strength}★</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {kit.outline && (
                <div>
                  <div className="text-[10px] uppercase mb-sp-1" style={{ color: "var(--fg-tertiary)" }}>
                    主线大纲 <span className="ml-1 normal-case">仅供参考，不会写入作品</span>
                  </div>
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
