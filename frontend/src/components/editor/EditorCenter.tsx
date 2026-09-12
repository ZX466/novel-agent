"use client";

/**
 * Center-column editor chrome: chapter title bar, loading strip, empty state,
 * export/display-settings overlay, and the Tiptap content area.
 */
import { EditorContent } from "@tiptap/react";
import type { Editor as TiptapEditor } from "@tiptap/react";

import { FormatToolbar } from "@/components/FormatToolbar";
import { EditorDisplaySettings } from "@/components/EditorDisplaySettings";
import { ExportMenu } from "@/components/editor/ExportMenu";
import type { SafetyScanReport } from "@/lib/safety";
import type { ExportFormat } from "@/lib/export";
import {
  DISPLAY_FONT_SIZES,
  DISPLAY_LINE_HEIGHTS,
  DISPLAY_WIDTHS,
  type EditorDisplay,
} from "@/components/EditorDisplaySettings";
import type { ChapterRead } from "@/lib/types";

interface EditorCenterProps {
  editor: TiptapEditor | null;
  display: EditorDisplay;
  onDisplayChange: (d: EditorDisplay) => void;
  activeChapter: ChapterRead | null;
  activeChapterLoading: boolean;
  hasChapters: boolean;
  chaptersLoading: boolean;
  currentText: string;
  docId: number;
  onRadarPreflight: (report: SafetyScanReport, fmt: ExportFormat) => void;
}

export function EditorCenter(props: EditorCenterProps) {
  const {
    editor, display, onDisplayChange, activeChapter, activeChapterLoading,
    hasChapters, chaptersLoading, currentText, docId, onRadarPreflight,
  } = props;

  return (
    <section className="flex flex-col h-full overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Chapter title */}
      {activeChapter && (
        <div
          className="px-sp-5 py-sp-2 border-b flex items-center gap-sp-2 shrink-0"
          style={{ background: "var(--surface)", borderColor: "var(--border-subtle)" }}
        >
          <span className="text-[11px] font-medium" style={{ color: "var(--fg-secondary)" }}>
            当前章节：
          </span>
          <span className="text-[13px] font-display font-semibold" style={{ color: "var(--fg)" }}>
            {activeChapter.title}
          </span>
        </div>
      )}

      {/* Loading */}
      {activeChapterLoading && (
        <div className="px-sp-5 py-sp-1 text-xs flex items-center gap-sp-2 shrink-0" style={{ color: "var(--accent)", background: "var(--accent-bg)" }}>
          <span className="w-[5px] h-[5px] rounded-full" style={{ background: "var(--accent)", animation: "pulse 1.2s infinite" }} />
          加载章节中…
        </div>
      )}

      {/* No chapter selected */}
      {!activeChapter && !chaptersLoading && !hasChapters && (
        <div className="flex-1 flex flex-col items-center justify-center gap-sp-4" style={{ color: "var(--muted)" }}>
          <svg className="w-14 h-14" style={{ color: "var(--border)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <p className="text-[13px]">暂无章节，点击左侧大纲中的「+」开始</p>
        </div>
      )}

      {/* Editor content */}
      {editor && (activeChapter || hasChapters) && (
        <>
          <FormatToolbar editor={editor} />
          <div className="flex-1 overflow-y-auto px-sp-8 py-sp-6 relative" style={{ background: "var(--bg-warm)" }}>
            {/* Export (F3) + display comfort settings (font / line-height / width) */}
            <div className="absolute top-sp-2 right-sp-3 z-20 flex items-center gap-sp-1">
              <ExportMenu
                docId={docId}
                activeChapterId={activeChapter?.id ?? null}
                activeChapterTitle={activeChapter?.title ?? null}
                currentText={currentText}
                onRadarPreflight={onRadarPreflight}
              />
              <EditorDisplaySettings display={display} onChange={onDisplayChange} />
            </div>
            <div
              className="mx-auto font-editor"
              style={{
                color: "var(--fg-secondary)",
                caretColor: "var(--accent)",
                fontSize: DISPLAY_FONT_SIZES[display.fontSize],
                lineHeight: DISPLAY_LINE_HEIGHTS[display.lineHeight],
                maxWidth: DISPLAY_WIDTHS[display.width],
              }}
            >
              <EditorContent editor={editor} />
            </div>
          </div>
        </>
      )}
    </section>
  );
}
