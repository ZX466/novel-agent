"use client";

import { useProviderConfig } from "@/hooks/use-provider-config";
import { SettingsDialog } from "@/components/SettingsDialog";
import { listDocuments, createDocument, deleteDocument, restoreDocument, permanentDeleteDocument } from "@/lib/documents";
import type { EditorDocListItem, DocumentListFilters, WorkTypeTabKey } from "@/lib/types";
import { ApiError, DOC_TYPE_CATEGORY_MAP, WORK_TYPE_TABS } from "@/lib/types";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

export default function NovelsPage() {
  const router = useRouter();
  const { isConfigured } = useProviderConfig();
  const [settingsOpen, setSettingsOpen] = useState(false);

  // List state
  const [items, setItems] = useState<EditorDocListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  // Filters
  const [activeTab, setActiveTab] = useState<WorkTypeTabKey>("all");
  const [search, setSearch] = useState("");
  const [showTrash, setShowTrash] = useState(false);
  const [page, setPage] = useState(0);
  const pageSize = 20;

  // Create dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newType, setNewType] = useState("novel");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Build filters from UI state
  const filters: DocumentListFilters = useMemo(() => {
    const f: DocumentListFilters = {
      limit: pageSize,
      offset: page * pageSize,
    };
    if (activeTab !== "all") f.type = activeTab;
    if (search.trim()) f.search = search.trim();
    if (showTrash) f.status = "deleted";
    return f;
  }, [activeTab, search, page, showTrash]);

  const fetchList = useCallback(async (f: DocumentListFilters) => {
    setLoading(true);
    setListError(null);
    try {
      const res = await listDocuments(f);
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      setListError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setPage(0);
  }, [activeTab, search, showTrash]);

  useEffect(() => {
    void fetchList(filters);
  }, [filters, fetchList]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const handleCreate = async () => {
    if (!newTitle.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const doc = await createDocument({
        title: newTitle.trim(),
        content_html: "",
        content_text: "",
        doc_type: newType,
        category: DOC_TYPE_CATEGORY_MAP[newType] ?? "",
      });
      setCreateOpen(false);
      setNewTitle("");
      router.push(`/novels/${doc.id}/editor`);
    } catch (e) {
      setCreateError(e instanceof ApiError ? e.message : "创建失败");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: number, name: string) => {
    if (!window.confirm(`将 "${name || "未命名"}" 移入回收站？`)) return;
    try {
      await deleteDocument(id);
      setItems((prev) => prev.filter((d) => d.id !== id));
      setTotal((t) => Math.max(0, t - 1));
    } catch (e) {
      alert(e instanceof Error ? e.message : "删除失败");
    }
  };

  const handleRestore = async (id: number) => {
    try {
      await restoreDocument(id);
      void fetchList(filters);
    } catch (e) {
      alert(e instanceof Error ? e.message : "恢复失败");
    }
  };

  const handlePermanentDelete = async (id: number, name: string) => {
    if (!window.confirm(`永久删除 "${name || "未命名"}"？此操作不可撤销。`)) return;
    try {
      await permanentDeleteDocument(id);
      setItems((prev) => prev.filter((d) => d.id !== id));
      setTotal((t) => Math.max(0, t - 1));
    } catch (e) {
      alert(e instanceof Error ? e.message : "删除失败");
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden px-sp-6 py-sp-6" style={{ background: "var(--bg)" }}>
      {/* Header */}
      <div className="flex items-center gap-sp-4 mb-sp-5 shrink-0 flex-wrap">
        <h1
          className="font-display text-[22px] font-semibold"
          style={{ color: "var(--fg)", letterSpacing: "-0.02em" }}
        >
          我的作品
        </h1>

        {/* Search */}
        <div className="ml-auto flex items-center gap-sp-3">
          <div
            className="flex items-center px-sp-3 py-sp-1.5 border rounded-md transition-all"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ color: "var(--muted)" }}
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索作品…"
              className="bg-transparent outline-none text-[12px] ml-sp-2 w-[120px]"
              style={{ color: "var(--fg)" }}
            />
          </div>

          {/* Recycle bin toggle */}
          <button
            type="button"
            onClick={() => setShowTrash((v) => !v)}
            className="px-sp-3 py-sp-1.5 rounded-sm text-[11px] font-medium border transition-colors"
            style={{
              borderColor: showTrash ? "var(--accent-muted)" : "var(--border)",
              background: showTrash ? "var(--accent-bg)" : "transparent",
              color: showTrash ? "var(--accent)" : "var(--muted)",
            }}
          >
            {showTrash ? "退出回收站" : "回收站"}
          </button>

          {/* New button */}
          {!showTrash && (
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="px-sp-4 py-sp-2 rounded-sm text-[12px] font-medium transition-all"
              style={{ background: "var(--accent)", color: "var(--bg)", letterSpacing: "0.02em" }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "var(--accent-hover)";
                e.currentTarget.style.transform = "translateY(-1px)";
                e.currentTarget.style.boxShadow = "var(--shadow-glow)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "var(--accent)";
                e.currentTarget.style.transform = "translateY(0)";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              + 新建作品
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      {!showTrash && (
        <div className="flex gap-sp-1 mb-sp-5 shrink-0">
          {WORK_TYPE_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className="px-sp-3 py-sp-1.5 rounded-sm text-[12px] font-medium border transition-colors"
              style={{
                borderColor: activeTab === tab.key ? "var(--accent-muted)" : "var(--border)",
                background: activeTab === tab.key ? "var(--accent-bg)" : "transparent",
                color: activeTab === tab.key ? "var(--accent)" : "var(--muted)",
              }}
              onMouseEnter={(e) => {
                if (activeTab !== tab.key) {
                  e.currentTarget.style.borderColor = "var(--border-hairline)";
                  e.currentTarget.style.color = "var(--fg-secondary)";
                }
              }}
              onMouseLeave={(e) => {
                if (activeTab !== tab.key) {
                  e.currentTarget.style.borderColor = "var(--border)";
                  e.currentTarget.style.color = "var(--muted)";
                }
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {/* Loading skeleton */}
        {loading && (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-sp-4 p-sp-1">
            {[0, 1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="h-[200px] rounded-md"
                style={{
                  background:
                    "linear-gradient(90deg, var(--surface) 25%, var(--surface-2) 50%, var(--surface) 75%)",
                  backgroundSize: "200% 100%",
                  animation: "shimmer 1.8s infinite",
                }}
              />
            ))}
          </div>
        )}

        {/* Error */}
        {!loading && listError && (
          <div
            className="flex items-start gap-sp-3 p-sp-4 rounded-md text-xs max-w-[400px] mx-auto mt-sp-10"
            style={{
              background: "oklch(0.60 0.16 25 / 0.08)",
              border: "1px solid oklch(0.60 0.16 25 / 0.15)",
              color: "var(--danger)",
            }}
          >
            <span className="flex-1">{listError}</span>
            <button
              type="button"
              onClick={() => void fetchList(filters)}
              className="font-medium underline underline-offset-2"
            >
              重试
            </button>
          </div>
        )}

        {/* Empty state */}
        {!loading && !listError && items.length === 0 && (
          <div
            className="flex flex-col items-center justify-center p-sp-10 text-center gap-sp-4 mt-sp-10"
            style={{ color: "var(--muted)" }}
          >
            <svg
              className="w-14 h-14 opacity-60"
              style={{ color: "var(--border)" }}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
            <p className="text-[13px]">
              {showTrash ? "回收站为空" : "还没有作品"}
            </p>
            {!showTrash && (
              <button
                type="button"
                onClick={() => setCreateOpen(true)}
                className="px-sp-4 py-sp-2 rounded-sm text-[12px] font-medium border transition-colors"
                style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
              >
                + 创建第一部作品
              </button>
            )}
          </div>
        )}

        {/* Card grid */}
        {!loading && !listError && items.length > 0 && (
          <div
            className="grid gap-sp-4 p-sp-1"
            style={{
              gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
            }}
          >
            {items.map((doc, i) => (
              <NovelCard
                key={doc.id}
                doc={doc}
                index={i}
                isTrash={showTrash}
                onOpen={() => router.push(`/novels/${doc.id}/editor`)}
                onDelete={() => void handleDelete(doc.id, doc.title)}
                onRestore={() => void handleRestore(doc.id)}
                onPermanentDelete={() =>
                  void handlePermanentDelete(doc.id, doc.title)
                }
              />
            ))}
          </div>
        )}
      </div>

      {/* Pagination */}
      {!loading && !listError && total > pageSize && (
        <div
          className="flex items-center justify-between pt-sp-4 border-t shrink-0 mt-sp-4"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="px-sp-3 py-sp-1.5 rounded-sm text-[11px] font-medium border transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
          >
            ← 上一页
          </button>
          <div className="flex items-center gap-sp-1">
            {Array.from({ length: totalPages }, (_, i) => i).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPage(p)}
                className="w-7 h-7 flex items-center justify-center rounded-sm text-[11px] font-medium transition-colors"
                style={{
                  background: p === page ? "var(--accent-bg)" : "transparent",
                  color: p === page ? "var(--accent)" : "var(--muted)",
                }}
              >
                {p + 1}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="px-sp-3 py-sp-1.5 rounded-sm text-[11px] font-medium border transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
          >
            下一页 →
          </button>
        </div>
      )}

      {/* Create dialog */}
      {createOpen && (
        <CreateDialog
          title={newTitle}
          onTitleChange={setNewTitle}
          docType={newType}
          onDocTypeChange={setNewType}
          error={createError}
          loading={creating}
          onConfirm={() => void handleCreate()}
          onClose={() => {
            setCreateOpen(false);
            setCreateError(null);
          }}
        />
      )}

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}

// ── Novel card ──────────────────────────────────────────────────────────

function NovelCard({
  doc,
  index,
  isTrash,
  onOpen,
  onDelete,
  onRestore,
  onPermanentDelete,
}: {
  doc: EditorDocListItem;
  index: number;
  isTrash: boolean;
  onOpen: () => void;
  onDelete: () => void;
  onRestore: () => void;
  onPermanentDelete: () => void;
}) {
  const [hover, setHover] = useState(false);

  const typeLabel = DOC_TYPE_CATEGORY_MAP[doc.doc_type] ?? doc.doc_type;
  const wordCountDisplay =
    doc.word_count >= 10000
      ? `${(doc.word_count / 10000).toFixed(1).replace(/\.0$/, "")}万`
      : doc.word_count >= 1000
        ? `${(doc.word_count / 1000).toFixed(1).replace(/\.0$/, "")}k`
        : String(doc.word_count);

  const coverBg = doc.cover_url
    ? `url(${doc.cover_url})`
    : "linear-gradient(135deg, var(--surface-2) 0%, var(--surface-3) 100%)";

  return (
    <div
      className="flex flex-col rounded-md border overflow-hidden cursor-pointer transition-all"
      style={{
        borderColor: hover ? "var(--border-hairline)" : "var(--border-subtle)",
        boxShadow: hover ? "var(--shadow-md)" : "none",
        background: "var(--surface)",
        animation: `fadeInUp 0.35s var(--ease-out) ${index * 50}ms both`,
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={isTrash ? undefined : onOpen}
      role={isTrash ? undefined : "button"}
      tabIndex={isTrash ? undefined : 0}
      onKeyDown={(e) => {
        if (!isTrash && (e.key === "Enter" || e.key === " ")) onOpen();
      }}
    >
      {/* Cover */}
      <div
        className="w-full aspect-[3/4] flex items-center justify-center relative"
        style={{
          background: coverBg,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        {!doc.cover_url && (
          <span
            className="text-[22px] font-display font-semibold opacity-30"
            style={{ color: "var(--fg)" }}
          >
            {doc.title.charAt(0) || "?"}
          </span>
        )}
        {/* Type badge */}
        <span
          className="absolute top-sp-2 right-sp-2 px-sp-2 py-[2px] rounded-sm text-[9px] font-semibold uppercase"
          style={{
            background: "oklch(0 0 0 / 0.55)",
            color: "var(--fg)",
            backdropFilter: "blur(8px)",
            letterSpacing: "0.06em",
          }}
        >
          {typeLabel}
        </span>
      </div>

      {/* Info */}
      <div className="p-sp-3 flex flex-col gap-sp-1.5">
        <span
          className="text-[13px] font-medium truncate"
          style={{ color: "var(--fg)" }}
        >
          {doc.title || "未命名"}
        </span>
        <div className="flex items-center gap-sp-2">
          <span
            className="text-[10px] tabular-nums"
            style={{ color: "var(--fg-tertiary)", fontFamily: "var(--font-mono)" }}
          >
            {wordCountDisplay}字
          </span>
        </div>

        {/* Action buttons */}
        {isTrash ? (
          <div className="flex gap-sp-1.5 mt-sp-1">
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onRestore(); }}
              className="flex-1 py-sp-1 rounded-sm text-[10px] font-medium border transition-colors"
              style={{ borderColor: "var(--success)", color: "var(--success)", background: "oklch(0.68 0.14 155 / 0.08)" }}
            >
              恢复
            </button>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onPermanentDelete(); }}
              className="flex-1 py-sp-1 rounded-sm text-[10px] font-medium border transition-colors"
              style={{ borderColor: "var(--danger)", color: "var(--danger)", background: "oklch(0.60 0.16 25 / 0.08)" }}
            >
              永久删除
            </button>
          </div>
        ) : (
          hover && (
            <div className="flex gap-sp-1.5 mt-sp-1">
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onOpen(); }}
                className="flex-1 py-sp-1 rounded-sm text-[10px] font-medium border transition-colors"
                style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
              >
                打开
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onDelete(); }}
                className="py-sp-1 px-sp-2 rounded-sm text-[10px] border transition-colors"
                style={{ borderColor: "var(--border)", color: "var(--muted)" }}
              >
                删除
              </button>
            </div>
          )
        )}
      </div>
    </div>
  );
}

// ── Create dialog ───────────────────────────────────────────────────────

function CreateDialog({
  title,
  onTitleChange,
  docType,
  onDocTypeChange,
  error,
  loading,
  onConfirm,
  onClose,
}: {
  title: string;
  onTitleChange: (v: string) => void;
  docType: string;
  onDocTypeChange: (v: string) => void;
  error: string | null;
  loading: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-sp-6"
      style={{ background: "oklch(0 0 0 / 0.60)", backdropFilter: "blur(4px)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-[400px] rounded-lg border p-sp-6 flex flex-col gap-sp-4"
        style={{ background: "var(--surface)", borderColor: "var(--border-hairline)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          className="font-display text-[18px] font-semibold"
          style={{ color: "var(--fg)" }}
        >
          新建作品
        </h2>

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
            onChange={(e) => onTitleChange(e.target.value)}
            placeholder="未命名作品"
            className="px-sp-4 py-sp-3 border rounded-md text-[14px] outline-none transition-all"
            style={{ background: "var(--bg)", borderColor: "var(--border)", color: "var(--fg)" }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = "var(--accent-muted)";
              e.currentTarget.style.boxShadow = "0 0 0 2px var(--accent-glow)";
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = "var(--border)";
              e.currentTarget.style.boxShadow = "none";
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && title.trim()) onConfirm();
              if (e.key === "Escape") onClose();
            }}
            disabled={loading}
            autoFocus
          />
        </div>

        <div className="flex flex-col gap-sp-1.5">
          <label
            className="text-[11px] font-semibold uppercase"
            style={{ color: "var(--fg-tertiary)", letterSpacing: "0.08em" }}
          >
            类型
          </label>
          <div className="flex gap-sp-2">
            {(["novel", "short", "script", "video"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => onDocTypeChange(t)}
                className="px-sp-3 py-sp-2 rounded-sm text-[12px] font-medium border transition-all"
                style={{
                  borderColor: docType === t ? "var(--accent-muted)" : "var(--border)",
                  background: docType === t ? "var(--accent-bg)" : "transparent",
                  color: docType === t ? "var(--accent)" : "var(--fg-tertiary)",
                }}
                disabled={loading}
              >
                {DOC_TYPE_CATEGORY_MAP[t] ?? t}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div
            className="px-sp-3 py-sp-2 rounded-md text-xs"
            style={{ color: "var(--danger)", background: "oklch(0.60 0.16 25 / 0.08)" }}
          >
            {error}
          </div>
        )}

        <div className="flex justify-end gap-sp-3 mt-sp-2">
          <button
            type="button"
            onClick={onClose}
            className="px-sp-4 py-sp-2 rounded-sm text-[12px] font-medium border transition-colors"
            style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
            disabled={loading}
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!title.trim() || loading}
            className="px-sp-5 py-sp-2 rounded-sm text-[12px] font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ background: "var(--accent)", color: "var(--bg)" }}
          >
            {loading ? "创建中…" : "创建"}
          </button>
        </div>
      </div>
    </div>
  );
}
