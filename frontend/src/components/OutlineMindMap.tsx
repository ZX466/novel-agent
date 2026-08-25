"use client";

import { useRef, useState } from "react";

import type { ChapterListItem } from "@/lib/types";

interface OutlineMindMapProps {
  chapters: ChapterListItem[];
  activeChapterId: number | null;
  onSelect: (chapterId: number) => void;
  onContinue: (chapterId: number) => void;
  onReorder: (orderedIds: Array<{ id: number; chapter_index: number }>) => void;
  onAdd: () => void;
}

const NODE_H = 52;
const NODE_GAP = 18;

/**
 * Outline mind-map view (R6-1): renders chapters as a vertical flow of
 * connected nodes — the outline as a visual story spine. Each node is a
 * chapter card with a direct "continue writing" entry, click-to-select and
 * drag-to-reorder, mirroring the list view's ordering semantics.
 */
export function OutlineMindMap({
  chapters,
  activeChapterId,
  onSelect,
  onContinue,
  onReorder,
  onAdd,
}: OutlineMindMapProps) {
  const dragItemRef = useRef<number | null>(null);
  const dragOverItemRef = useRef<number | null>(null);
  const [draggingId, setDraggingId] = useState<number | null>(null);

  const handleDragStart = (chapterId: number) => {
    dragItemRef.current = chapterId;
    setDraggingId(chapterId);
  };

  const handleDragEnter = (chapterId: number) => {
    dragOverItemRef.current = chapterId;
  };

  const handleDragEnd = () => {
    const fromId = dragItemRef.current;
    const toId = dragOverItemRef.current;
    dragItemRef.current = null;
    dragOverItemRef.current = null;
    setDraggingId(null);
    if (fromId == null || toId == null || fromId === toId) return;

    const fromIdx = chapters.findIndex((c) => c.id === fromId);
    const toIdx = chapters.findIndex((c) => c.id === toId);
    if (fromIdx === -1 || toIdx === -1) return;

    const reordered = chapters.filter((c) => c.id !== fromId);
    // After removing the source, indices at/after fromIdx shift down by one,
    // so the drop index must be corrected when dragging downward.
    reordered.splice(toIdx > fromIdx ? toIdx - 1 : toIdx, 0, chapters[fromIdx]);
    onReorder(reordered.map((c, i) => ({ id: c.id, chapter_index: i })));
  };

  if (chapters.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center h-full p-sp-8 text-center gap-sp-3"
        style={{ color: "var(--muted)" }}
      >
        <p className="text-[12px]">暂无章节，先添加章节后再查看脑图</p>
        <button
          type="button"
          onClick={onAdd}
          className="px-sp-3 py-sp-1.5 rounded-sm text-[11px] font-medium border transition-colors"
          style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
        >
          + 添加第一章
        </button>
      </div>
    );
  }

  const svgH = chapters.length * NODE_H + (chapters.length - 1) * NODE_GAP;

  return (
    <div className="relative w-full overflow-x-auto overflow-y-auto" style={{ minHeight: svgH }}>
      {/* Connection lines between consecutive chapter nodes. */}
      <svg
        className="absolute left-0 top-0 pointer-events-none"
        width="100%"
        height={svgH}
        aria-hidden
      >
        {chapters.slice(0, -1).map((_, i) => {
          const y1 = i * (NODE_H + NODE_GAP) + NODE_H;
          const y2 = (i + 1) * (NODE_H + NODE_GAP);
          return (
            <g key={i}>
              <line
                x1="24"
                y1={y1}
                x2="24"
                y2={y2}
                stroke="var(--border-hairline)"
                strokeWidth="1.5"
                strokeDasharray="3 3"
              />
              <path
                d={`M 20 ${y2 - 5} L 24 ${y2} L 28 ${y2 - 5}`}
                fill="none"
                stroke="var(--border-hairline)"
                strokeWidth="1.5"
              />
            </g>
          );
        })}
      </svg>

      <div className="relative py-sp-1 pr-sp-2">
        {chapters.map((ch, i) => {
          const isActive = ch.id === activeChapterId;
          const isDragging = ch.id === draggingId;
          return (
            <div
              key={ch.id}
              className="relative mb-0"
              style={{ height: NODE_H, marginBottom: NODE_GAP }}
              draggable
              onDragStart={() => handleDragStart(ch.id)}
              onDragEnter={() => handleDragEnter(ch.id)}
              onDragEnd={handleDragEnd}
              onDragOver={(e) => e.preventDefault()}
            >
              <div
                role="button"
                tabIndex={0}
                aria-pressed={isActive}
                className="flex items-center gap-sp-2 pl-sp-3 pr-sp-2 h-full rounded-md border cursor-pointer select-none transition-all outline-none focus-visible:ring-1"
                style={{
                  background: isActive ? "var(--accent-bg)" : "var(--surface)",
                  borderColor: isActive ? "var(--accent)" : "var(--border-hairline)",
                  opacity: isDragging ? 0.45 : 1,
                  boxShadow: isActive ? "0 0 0 1px var(--accent-muted)" : undefined,
                  marginLeft: 48,
                }}
                onClick={() => onSelect(ch.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(ch.id);
                  } else if (e.key === "ArrowUp" && i > 0) {
                    e.preventDefault();
                    const moved = [...chapters];
                    [moved[i - 1], moved[i]] = [moved[i], moved[i - 1]];
                    onReorder(moved.map((c, idx) => ({ id: c.id, chapter_index: idx })));
                  } else if (e.key === "ArrowDown" && i < chapters.length - 1) {
                    e.preventDefault();
                    const moved = [...chapters];
                    [moved[i], moved[i + 1]] = [moved[i + 1], moved[i]];
                    onReorder(moved.map((c, idx) => ({ id: c.id, chapter_index: idx })));
                  }
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.background = "var(--surface-2)";
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.background = "var(--surface)";
                }}
              >
                {/* Sequence badge */}
                <span
                  className="shrink-0 w-[20px] h-[20px] rounded-full flex items-center justify-center text-[10px] font-semibold tabular-nums"
                  style={{
                    background: isActive ? "var(--accent)" : "var(--surface-2)",
                    color: isActive ? "var(--bg)" : "var(--muted)",
                    border: "1px solid var(--border-hairline)",
                  }}
                >
                  {i + 1}
                </span>

                {/* Drag handle */}
                <span
                  className="shrink-0 text-[9px] cursor-grab opacity-0 hover:opacity-70 transition-opacity"
                  style={{ color: "var(--muted)" }}
                  title="拖拽排序"
                >
                  ⠿
                </span>

                <span
                  className="flex-1 min-w-0 text-[12px] truncate leading-[1.4]"
                  style={{
                    color: isActive ? "var(--fg)" : "var(--fg-secondary)",
                    fontWeight: isActive ? 500 : 400,
                  }}
                >
                  {ch.title || "未命名章节"}
                </span>

                {ch.word_count > 0 && (
                  <span
                    className="text-[9px] tabular-nums shrink-0 opacity-60"
                    style={{ color: "var(--fg-tertiary)", fontFamily: "var(--font-mono)" }}
                  >
                    {ch.word_count}
                  </span>
                )}

                {/* Direct continue-writing entry */}
                <button
                  type="button"
                  className="shrink-0 w-[24px] h-[24px] flex items-center justify-center rounded-sm text-[12px] transition-colors"
                  style={{ color: "var(--muted)" }}
                  title="直接续写此章节"
                  aria-label={`续写章节 ${ch.title || "未命名章节"}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onContinue(ch.id);
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "var(--surface-2)";
                    e.currentTarget.style.color = "var(--accent)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "transparent";
                    e.currentTarget.style.color = "var(--muted)";
                  }}
                >
                  ✍️
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
