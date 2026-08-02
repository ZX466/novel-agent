"use client";

import type { EditorDocListItem } from "@/lib/types";

interface DocumentListProps {
  docs: EditorDocListItem[];
  activeId?: number | null;
  activeWordCount?: number | null;
  loading: boolean;
  error: string | null;
  onSelect: (id: number) => void;
  onNew: () => void;
  onDelete: (id: number) => void;
  onRetry: () => void;
}

function formatWordCount(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(n);
}

export function DocumentList({
  docs,
  activeId,
  activeWordCount,
  loading,
  error,
  onSelect,
  onNew,
  onDelete,
  onRetry,
}: DocumentListProps) {
  return (
    <aside
      className="sidebar flex flex-col h-full overflow-hidden"
      style={{ background: "var(--bg)" }}
    >
      {/* Panel header */}
      <div
        className="px-sp-5 py-sp-3 border-b flex items-center gap-sp-2 shrink-0"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
        }}
      >
        <span
          className="text-[10px] font-semibold uppercase"
          style={{ color: "var(--fg-tertiary)", letterSpacing: "0.1em" }}
        >
          文稿
        </span>
        <button
          type="button"
          onClick={onNew}
          className="ml-auto text-[11px] font-medium px-3 py-[5px] rounded-sm transition-all"
          style={{
            background: "var(--accent)",
            color: "var(--bg)",
            letterSpacing: "0.02em",
          }}
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
          + 新建
        </button>
      </div>

      {/* Panel body */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {/* Loading skeleton */}
        {loading && (
          <div className="p-sp-3 space-y-sp-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-[14px] rounded-[3px]"
                style={{
                  background: "linear-gradient(90deg, var(--surface) 25%, var(--surface-2) 50%, var(--surface) 75%)",
                  backgroundSize: "200% 100%",
                  animation: "shimmer 1.8s infinite",
                  width: i === 0 ? "50%" : i === 1 ? "85%" : "60%",
                }}
              />
            ))}
          </div>
        )}

        {/* Error state */}
        {!loading && error && (
          <div className="p-sp-3">
            <div
              className="flex items-start gap-sp-3 p-sp-4 rounded-md text-xs"
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
              <span className="flex-1">加载失败：{error}</span>
              <button
                type="button"
                onClick={onRetry}
                className="font-medium underline underline-offset-2 shrink-0 px-1 py-0.5 rounded-[3px] transition-colors"
                style={{ color: "var(--danger)" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "oklch(0.60 0.16 25 / 0.10)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                重试
              </button>
            </div>
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && docs.length === 0 && (
          <div
            className="flex flex-col items-center justify-center p-sp-10 text-center gap-sp-3"
            style={{ color: "var(--muted)" }}
          >
            <svg
              className="w-9 h-9 opacity-60"
              style={{ color: "var(--border)" }}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
            <p className="text-[13px] leading-relaxed max-w-[200px]">
              还没有文档
            </p>
            <p className="text-[11px]" style={{ color: "var(--fg-tertiary)" }}>
              点击上方「+ 新建」开始写作
            </p>
          </div>
        )}

        {/* Document list */}
        {!loading && !error && docs.length > 0 && (
          <div className="p-sp-2" role="listbox" aria-label="文档列表">
            {docs.map((doc, i) => {
              const isActive = doc.id === activeId;
              return (
                <div
                  key={doc.id}
                  role="option"
                  aria-selected={isActive}
                  className="group flex items-center px-sp-3 py-sp-3 rounded-sm cursor-pointer relative mb-px transition-all"
                  style={{
                    gap: "12px",
                    background: isActive ? "var(--accent-bg)" : "transparent",
                    animation: `slideInLeft 0.25s var(--ease-out) ${i * 30}ms both`,
                  }}
                  onClick={() => onSelect(doc.id)}
                  onMouseEnter={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.background = "var(--surface)";
                    }
                    e.currentTarget.style.paddingLeft = "calc(12px + 2px)";
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.background = "transparent";
                    }
                    e.currentTarget.style.paddingLeft = "12px";
                  }}
                >
                  {/* Active indicator bar */}
                  {isActive && (
                    <span
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-[2px] rounded-px"
                      style={{
                        height: "55%",
                        background: "var(--accent)",
                      }}
                    />
                  )}

                  {/* Doc icon */}
                  <svg
                    className="w-[15px] h-[15px] shrink-0 opacity-70"
                    style={{ color: "var(--muted)" }}
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>

                  <span
                    className="flex-1 text-[13px] truncate leading-[1.4]"
                    style={{
                      color: isActive ? "var(--fg)" : "var(--fg-secondary)",
                      fontWeight: isActive ? 500 : 400,
                    }}
                  >
                    {doc.title || "(未命名)"}
                  </span>

                  {isActive && activeWordCount != null && (
                    <span
                      className="text-[10px] tabular-nums shrink-0"
                      style={{
                        color: "var(--fg-tertiary)",
                        fontFamily: "var(--font-mono)",
                        letterSpacing: "0.02em",
                      }}
                    >
                      {formatWordCount(activeWordCount)}字
                    </span>
                  )}

                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (window.confirm(`删除 "${doc.title || "未命名"}"？此操作不可撤销。`)) {
                        onDelete(doc.id);
                      }
                    }}
                    className="opacity-0 group-hover:opacity-100 text-[11px] px-[5px] py-[2px] rounded-[3px] transition-all"
                    style={{ color: "var(--muted)" }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.color = "var(--danger)";
                      e.currentTarget.style.background = "oklch(0.60 0.16 25 / 0.08)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.color = "var(--muted)";
                      e.currentTarget.style.background = "transparent";
                    }}
                    aria-label={`删除 ${doc.title || "未命名"}`}
                  >
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}
