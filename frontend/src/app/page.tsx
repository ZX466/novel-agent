"use client";

import Link from "next/link";
import { useState } from "react";

import { useProviderConfig } from "@/hooks/use-provider-config";
import { SettingsDialog } from "@/components/SettingsDialog";
import { ApiError, DOC_TYPE_CATEGORY_MAP } from "@/lib/types";
import { createDocument } from "@/lib/documents";
import { useRouter } from "next/navigation";

export default function HomePage() {
  const router = useRouter();
  const { isConfigured, loaded } = useProviderConfig();
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Quick-start form fields
  const [title, setTitle] = useState("");
  const [docType, setDocType] = useState<string>("novel");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const docTypeOptions = [
    { value: "short", label: "短篇" },
    { value: "novel", label: "长篇" },
    { value: "script", label: "剧本" },
    { value: "video", label: "视频" },
  ];

  const handleCreate = async () => {
    if (!title.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const doc = await createDocument({
        title: title.trim(),
        content_html: "",
        content_text: "",
        doc_type: docType,
        category: DOC_TYPE_CATEGORY_MAP[docType] ?? "",
      });
      router.push(`/novels/${doc.id}/editor`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "创建失败");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center h-full px-sp-6 py-sp-10 overflow-auto" style={{ background: "var(--bg)" }}>
      {/* Hero */}
      <div className="max-w-[560px] w-full text-center mb-sp-10">
        <h1
          className="font-display text-[32px] font-semibold mb-sp-3"
          style={{ color: "var(--fg)", letterSpacing: "-0.02em" }}
        >
          开始创作
        </h1>
        <p
          className="text-[14px] leading-relaxed mb-sp-6"
          style={{ color: "var(--muted)" }}
        >
          输入作品名、选择类型，即可开始写作。AI 三阶段流水线将为你
          起草、精修、评估。
        </p>

        {/* API status pill */}
        {loaded && !isConfigured && (
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="inline-flex items-center gap-sp-2 px-sp-3 py-sp-1.5 rounded-md text-xs font-medium border transition-colors mb-sp-6"
            style={{
              borderColor: "oklch(0.74 0.10 85 / 0.30)",
              color: "var(--warn)",
              background: "oklch(0.74 0.10 85 / 0.06)",
            }}
          >
            <span
              className="w-[6px] h-[6px] rounded-full"
              style={{ background: "var(--warn)" }}
            />
            API 未配置 — 点击设置
          </button>
        )}

        {loaded && isConfigured && (
          <span
            className="inline-flex items-center gap-sp-2 px-sp-3 py-sp-1.5 rounded-md text-xs font-medium mb-sp-6"
            style={{
              color: "var(--success)",
              background: "oklch(0.68 0.14 155 / 0.08)",
            }}
          >
            <span
              className="w-[6px] h-[6px] rounded-full"
              style={{ background: "var(--success)", boxShadow: "0 0 8px oklch(0.68 0.14 155 / 0.40)" }}
            />
            API 已就绪
          </span>
        )}
      </div>

      {/* Quick-start card */}
      <div
        className="w-full max-w-[480px] rounded-lg border p-sp-6 flex flex-col gap-sp-4"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
        }}
      >
        {/* Title input */}
        <div className="flex flex-col gap-sp-1.5">
          <label
            className="text-[11px] font-semibold uppercase"
            style={{ color: "var(--fg-tertiary)", letterSpacing: "0.08em" }}
          >
            作品名
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="给你的作品起个名字…"
            className="px-sp-4 py-sp-3 border rounded-md text-[14px] outline-none transition-all"
            style={{
              background: "var(--bg)",
              borderColor: "var(--border)",
              color: "var(--fg)",
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = "var(--accent-muted)";
              e.currentTarget.style.boxShadow = "0 0 0 2px var(--accent-glow)";
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = "var(--border)";
              e.currentTarget.style.boxShadow = "none";
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && title.trim()) {
                void handleCreate();
              }
            }}
            disabled={creating}
            autoFocus
          />
        </div>

        {/* Work type */}
        <div className="flex flex-col gap-sp-1.5">
          <label
            className="text-[11px] font-semibold uppercase"
            style={{ color: "var(--fg-tertiary)", letterSpacing: "0.08em" }}
          >
            类型
          </label>
          <div className="flex gap-sp-2">
            {docTypeOptions.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setDocType(opt.value)}
                className="px-sp-3 py-sp-2 rounded-sm text-[12px] font-medium border transition-all"
                style={{
                  borderColor:
                    docType === opt.value
                      ? "var(--accent-muted)"
                      : "var(--border)",
                  background:
                    docType === opt.value ? "var(--accent-bg)" : "transparent",
                  color:
                    docType === opt.value
                      ? "var(--accent)"
                      : "var(--fg-tertiary)",
                }}
                onMouseEnter={(e) => {
                  if (docType !== opt.value) {
                    e.currentTarget.style.borderColor = "var(--border-hairline)";
                    e.currentTarget.style.color = "var(--fg-secondary)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (docType !== opt.value) {
                    e.currentTarget.style.borderColor = "var(--border)";
                    e.currentTarget.style.color = "var(--fg-tertiary)";
                  }
                }}
                disabled={creating}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Error */}
        {error && (
          <div
            className="px-sp-3 py-sp-2 rounded-md text-xs"
            style={{
              color: "var(--danger)",
              background: "oklch(0.60 0.16 25 / 0.08)",
              border: "1px solid oklch(0.60 0.16 25 / 0.15)",
            }}
          >
            {error}
          </div>
        )}

        {/* Submit */}
        <button
          type="button"
          onClick={() => void handleCreate()}
          disabled={!title.trim() || creating}
          className="w-full mt-sp-2 px-sp-4 py-sp-3 rounded-md text-[14px] font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed"
          style={{
            background: "var(--accent)",
            color: "var(--bg)",
            letterSpacing: "0.02em",
          }}
          onMouseEnter={(e) => {
            if (!e.currentTarget.disabled) {
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
          {creating ? "创建中…" : "开始创作"}
        </button>
      </div>

      {/* Secondary links */}
      <div className="flex gap-sp-4 mt-sp-8">
        <Link
          href="/novels"
          className="text-[12px] font-medium no-underline px-sp-4 py-sp-2 rounded-sm border transition-colors"
          style={{
            color: "var(--fg-secondary)",
            borderColor: "var(--border)",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = "var(--border-hairline)";
            e.currentTarget.style.color = "var(--fg)";
            e.currentTarget.style.background = "var(--surface)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "var(--border)";
            e.currentTarget.style.color = "var(--fg-secondary)";
            e.currentTarget.style.background = "transparent";
          }}
        >
          我的作品
        </Link>
      </div>

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
