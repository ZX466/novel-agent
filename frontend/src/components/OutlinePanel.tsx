"use client";

import { useCallback, useRef, useState } from "react";

import type { ChapterListItem } from "@/lib/types";

interface OutlinePanelProps {
  chapters: ChapterListItem[];
  activeChapterId: number | null;
  loading: boolean;
  outline?: string;
  onSaveOutline?: (text: string) => void;
  onExtractEntities?: () => void;
  extracting?: boolean;
  onSelect: (chapterId: number) => void;
  onAdd: () => void;
  onDelete: (chapterId: number) => void;
  onRename: (chapterId: number, newTitle: string) => void;
  onReorder: (orderedIds: Array<{ id: number; chapter_index: number }>) => void;
}

export function OutlinePanel({
  chapters,
  activeChapterId,
  loading,
  outline,
  onSaveOutline,
  onExtractEntities,
  extracting,
  onSelect,
  onAdd,
  onDelete,
  onRename,
  onReorder,
}: OutlinePanelProps) {
  const [contextMenu, setContextMenu] = useState<{
    chapterId: number;
    x: number;
    y: number;
  } | null>(null);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const dragItemRef = useRef<number | null>(null);
  const dragOverItemRef = useRef<number | null>(null);

  // Outline editing state.
  const [editingOutline, setEditingOutline] = useState(false);
  const [outlineDraft, setOutlineDraft] = useState(outline ?? "");
  // Sync draft when outline prop changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const prevOutlineRef = useRef(outline);
  if (outline !== prevOutlineRef.current) {
    prevOutlineRef.current = outline;
    setOutlineDraft(outline ?? "");
  }

  // Close context menu on outside click.
  const handleOverlayClick = useCallback(() => setContextMenu(null), []);

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, chapterId: number) => {
      e.preventDefault();
      setContextMenu({ chapterId, x: e.clientX, y: e.clientY });
    },
    [],
  );

  const handleDragStart = useCallback((chapterId: number) => {
    dragItemRef.current = chapterId;
  }, []);

  const handleDragEnter = useCallback((chapterId: number) => {
    dragOverItemRef.current = chapterId;
  }, []);

  const handleDragEnd = useCallback(() => {
    const fromId = dragItemRef.current;
    const toId = dragOverItemRef.current;
    dragItemRef.current = null;
    dragOverItemRef.current = null;
    if (fromId == null || toId == null || fromId === toId) return;

    const fromIdx = chapters.findIndex((c) => c.id === fromId);
    const toIdx = chapters.findIndex((c) => c.id === toId);
    if (fromIdx === -1 || toIdx === -1) return;

    // Build reordered list: remove fromId, insert at toIdx position.
    const reordered = chapters.filter((c) => c.id !== fromId);
    reordered.splice(toIdx, 0, chapters[fromIdx]);

    // Assign new sequential indices.
    const orderedIds = reordered.map((c, i) => ({
      id: c.id,
      chapter_index: i,
    }));
    onReorder(orderedIds);
  }, [chapters, onReorder]);

  const handleRenameCommit = useCallback(
    (chapterId: number) => {
      const trimmed = renameValue.trim();
      if (trimmed) {
        onRename(chapterId, trimmed);
      }
      setRenamingId(null);
      setRenameValue("");
    },
    [renameValue, onRename],
  );

  return (
    <aside
      className="flex flex-col h-full overflow-hidden"
      style={{ background: "var(--bg)" }}
    >
      {/* Header */}
      <div
        className="px-sp-4 py-sp-3 border-b flex items-center gap-sp-2 shrink-0"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
        }}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ color: "var(--muted)" }}
        >
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        </svg>
        <span
          className="text-[10px] font-semibold uppercase"
          style={{ color: "var(--fg-tertiary)", letterSpacing: "0.1em" }}
        >
          大纲
        </span>
        <span className="flex-1" />
        <button
          type="button"
          onClick={onAdd}
          className="w-6 h-6 flex items-center justify-center rounded-sm transition-colors"
          style={{ color: "var(--muted)" }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--surface-2)";
            e.currentTarget.style.color = "var(--fg)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent";
            e.currentTarget.style.color = "var(--muted)";
          }}
          title="添加章节"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>

      {/* Outline text — always visible */}
      <div
        className="px-sp-4 py-sp-3 border-b shrink-0 overflow-y-auto"
        style={{
          borderColor: "var(--border-subtle)",
          background: "var(--bg)",
          maxHeight: editingOutline ? "45%" : "30%",
        }}
      >
        <div className="flex items-center mb-sp-2">
          <span
            className="text-[10px] font-semibold uppercase flex-1"
            style={{ color: "var(--fg-tertiary)", letterSpacing: "0.08em" }}
          >
            总纲
          </span>
          <div className="flex gap-sp-1">
            <button
              type="button"
              onClick={onExtractEntities}
              disabled={extracting || !outline}
              className="text-[10px] px-sp-2 py-px rounded-sm transition-colors disabled:opacity-40"
              style={{
                color: "var(--accent)",
                border: "1px solid var(--accent)",
              }}
              title="从大纲提取角色、世界观和剧情事件"
            >
              {extracting ? "提取中…" : "AI 提取"}
            </button>
            <button
              type="button"
              onClick={() => {
                if (editingOutline) {
                  onSaveOutline?.(outlineDraft);
                  setEditingOutline(false);
                } else {
                  setEditingOutline(true);
                }
              }}
              className="text-[10px] px-sp-2 py-px rounded-sm transition-colors"
              style={{
                color: editingOutline ? "var(--bg)" : "var(--muted)",
                background: editingOutline ? "var(--accent)" : "transparent",
                border: editingOutline ? "none" : "1px solid var(--border)",
              }}
            >
              {editingOutline ? "保存" : "编辑"}
            </button>
          </div>
        </div>
        {editingOutline || !outline ? (
          <textarea
            value={outlineDraft}
            onChange={(e) => setOutlineDraft(e.target.value)}
            placeholder="在此编写或粘贴小说大纲…&#10;&#10;例如：&#10;1. 第一章 张三入宗&#10;   张三在青云宗拜入门下，开启修仙之路。&#10;2. 第二章 修炼突破&#10;   张三苦修三个月，终于突破练气期。"
            className="w-full min-h-[100px] text-[12px] leading-[1.7] bg-transparent border rounded-sm p-sp-2 outline-none resize-y"
            style={{
              color: "var(--fg-secondary)",
              borderColor: "var(--border)",
            }}
            onBlur={() => {
              // Auto-save on blur if there's content
              if (outlineDraft.trim() && outlineDraft !== outline) {
                onSaveOutline?.(outlineDraft);
              }
            }}
          />
        ) : (
          <p
            className="text-[12px] leading-[1.7] whitespace-pre-wrap cursor-pointer"
            style={{ color: "var(--fg-secondary)" }}
            onClick={() => setEditingOutline(true)}
            title="点击编辑"
          >
            {outline}
          </p>
        )}
      </div>

      {/* Chapter list */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {loading && (
          <div className="p-sp-3 space-y-sp-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-[14px] rounded-[3px]"
                style={{
                  background:
                    "linear-gradient(90deg, var(--surface) 25%, var(--surface-2) 50%, var(--surface) 75%)",
                  backgroundSize: "200% 100%",
                  animation: "shimmer 1.8s infinite",
                  width: i === 0 ? "50%" : i === 1 ? "85%" : "60%",
                }}
              />
            ))}
          </div>
        )}

        {!loading && chapters.length === 0 && (
          <div
            className="flex flex-col items-center p-sp-8 text-center gap-sp-3"
            style={{ color: "var(--muted)" }}
          >
            <p className="text-[12px]">暂无章节</p>
            <button
              type="button"
              onClick={onAdd}
              className="px-sp-3 py-sp-1.5 rounded-sm text-[11px] font-medium border transition-colors"
              style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
            >
              + 添加第一章
            </button>
          </div>
        )}

        {!loading && chapters.length > 0 && (
          <div className="p-sp-1.5">
            {chapters.map((ch, i) => {
              const isActive = ch.id === activeChapterId;
              const isRenaming = ch.id === renamingId;

              return (
                <div
                  key={ch.id}
                  className="group flex items-center gap-sp-2 px-sp-3 py-sp-2 rounded-sm cursor-pointer relative mb-px transition-all"
                  style={{
                    background: isActive ? "var(--accent-bg)" : "transparent",
                    animation: `slideInLeft 0.2s var(--ease-out) ${i * 30}ms both`,
                  }}
                  draggable
                  onDragStart={() => handleDragStart(ch.id)}
                  onDragEnter={() => handleDragEnter(ch.id)}
                  onDragEnd={handleDragEnd}
                  onDragOver={(e) => e.preventDefault()}
                  onClick={() => !isRenaming && onSelect(ch.id)}
                  onContextMenu={(e) => handleContextMenu(e, ch.id)}
                  onMouseEnter={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.background = "var(--surface)";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.background = "transparent";
                    }
                  }}
                >
                  {/* Active indicator */}
                  {isActive && (
                    <span
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-[2px] rounded-px"
                      style={{ height: "55%", background: "var(--accent)" }}
                    />
                  )}

                  {/* Drag handle */}
                  <span
                    className="shrink-0 text-[9px] cursor-grab opacity-0 group-hover:opacity-60 transition-opacity"
                    style={{ color: "var(--muted)" }}
                    title="拖拽排序"
                  >
                    ⠿
                  </span>

                  {/* Chapter icon */}
                  <svg
                    className="w-[13px] h-[13px] shrink-0 opacity-60"
                    style={{ color: isActive ? "var(--accent)" : "var(--muted)" }}
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

                  {isRenaming ? (
                    <input
                      type="text"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onBlur={() => handleRenameCommit(ch.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleRenameCommit(ch.id);
                        if (e.key === "Escape") { setRenamingId(null); setRenameValue(""); }
                      }}
                      className="flex-1 min-w-0 bg-transparent border-b text-[12px] outline-none"
                      style={{ borderColor: "var(--accent-muted)", color: "var(--fg)" }}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : (
                    <span
                      className="flex-1 text-[12px] truncate leading-[1.4] min-w-0"
                      style={{
                        color: isActive ? "var(--fg)" : "var(--fg-secondary)",
                        fontWeight: isActive ? 500 : 400,
                      }}
                    >
                      {ch.title || "未命名章节"}
                    </span>
                  )}

                  {/* Word count */}
                  <span
                    className="text-[9px] tabular-nums shrink-0 opacity-0 group-hover:opacity-60 transition-opacity"
                    style={{ color: "var(--fg-tertiary)", fontFamily: "var(--font-mono)" }}
                  >
                    {ch.word_count > 0 ? `${ch.word_count}` : ""}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Context menu overlay */}
      {contextMenu && (
        <div
          className="fixed inset-0 z-40"
          onClick={handleOverlayClick}
        >
          <div
            className="absolute z-50 py-sp-1 rounded-md border shadow-lg min-w-[120px]"
            style={{
              left: contextMenu.x,
              top: contextMenu.y,
              background: "var(--surface)",
              borderColor: "var(--border-hairline)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <ContextMenuItem
              label="重命名"
              onClick={() => {
                const ch = chapters.find((c) => c.id === contextMenu.chapterId);
                if (ch) {
                  setRenamingId(ch.id);
                  setRenameValue(ch.title);
                }
                setContextMenu(null);
              }}
            />
            <ContextMenuItem
              label="删除章节"
              danger
              onClick={() => {
                onDelete(contextMenu.chapterId);
                setContextMenu(null);
              }}
            />
          </div>
        </div>
      )}
    </aside>
  );
}

function ContextMenuItem({
  label,
  onClick,
  danger = false,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full px-sp-3 py-sp-1.5 text-left text-[12px] font-medium transition-colors"
      style={{ color: danger ? "var(--danger)" : "var(--fg-secondary)" }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = danger
          ? "oklch(0.60 0.16 25 / 0.10)"
          : "var(--surface-2)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "transparent";
      }}
    >
      {label}
    </button>
  );
}
