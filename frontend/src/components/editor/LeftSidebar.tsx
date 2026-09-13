"use client";

/**
 * Left sidebar: 7-tab strip (大纲/角色/世界观/剧情/关系图/时间线/一致性) plus
 * the Creative Kit (灵感套件) entry button, and the tab body mounting the
 * matching panel. `panelRefreshKey` remounts lore panels after extraction so
 * they re-fetch fresh data.
 */
import { CharacterPanel } from "@/components/CharacterPanel";
import { WorldSettingPanel } from "@/components/WorldSettingPanel";
import PlotEventPanel from "@/components/PlotEventPanel";
import { OutlinePanel } from "@/components/OutlinePanel";
import { RelationshipGraph } from "@/components/RelationshipGraph";
import { TimelineGraph } from "@/components/TimelineGraph";
import { ConsistencyPanel } from "@/components/ConsistencyPanel";
import type { ChapterListItem } from "@/lib/types";

export type LeftTab =
  | "outline"
  | "characters"
  | "world"
  | "events"
  | "graph"
  | "timeline"
  | "consistency";

const TABS: Array<{ key: LeftTab; label: string; title: string }> = [
  { key: "outline", label: "📖", title: "大纲" },
  { key: "characters", label: "👤", title: "角色" },
  { key: "world", label: "🌍", title: "世界观" },
  { key: "events", label: "📋", title: "剧情" },
  { key: "graph", label: "🕸", title: "关系图" },
  { key: "timeline", label: "⏳", title: "时间线" },
  { key: "consistency", label: "🛡", title: "一致性" },
];

interface LeftSidebarProps {
  leftTab: LeftTab;
  onTabChange: (tab: LeftTab) => void;
  panelRefreshKey: number;
  kitOpen: boolean;
  onOpenKit: () => void;
  docId: number;
  chapters: ChapterListItem[];
  activeChapterId: number | null;
  activeChapterTitle: string | null;
  chaptersLoading: boolean;
  outline: string | undefined;
  extracting: boolean;
  currentText: string;
  onSaveOutline: (text: string) => void;
  onExtractEntities: () => void;
  onSelectChapter: (id: number) => void;
  onAddChapter: () => void;
  onDeleteChapter: (id: number) => void;
  onRenameChapter: (id: number, title: string) => void;
  onReorder: (ids: Array<{ id: number; chapter_index: number }>) => void;
  onContinueChapter: (id: number) => void;
  /** Jump to /novels/[id]/graph with the given tab (fullscreen view). */
  onOpenFullscreen: (tab: "graph" | "timeline") => void;
  /** R10-⑨: AI 润色总纲 — sends the current outline through the rewrite
   *  pipeline and applies the polished text back to the outline editor. */
  onOutlinePolish?: (onDone: (polished: string) => void, onError: (msg: string) => void) => void;
}

export function LeftSidebar(props: LeftSidebarProps) {
  const {
    leftTab, onTabChange, panelRefreshKey, kitOpen, onOpenKit,
    docId, chapters, activeChapterId, activeChapterTitle, chaptersLoading,
    outline, extracting, currentText,
    onSaveOutline, onExtractEntities, onSelectChapter, onAddChapter,
    onDeleteChapter, onRenameChapter, onReorder, onContinueChapter,
    onOpenFullscreen, onOutlinePolish,
  } = props;

  return (
    <div className="flex flex-col h-full min-h-0" style={{ background: "var(--surface)" }}>
      {/* Tab strip */}
      <div
        className="flex shrink-0 border-b text-[11px]"
        style={{ borderColor: "var(--border-subtle)" }}
      >
        {TABS.map((t) => {
          const active = leftTab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => onTabChange(t.key)}
              title={t.title}
              className="flex-1 py-sp-2 text-center transition-colors"
              style={{
                color: active ? "var(--accent)" : "var(--muted)",
                borderBottom: active
                  ? "2px solid var(--accent)"
                  : "2px solid transparent",
                background: active ? "var(--bg)" : "transparent",
                fontSize: "13px",
              }}
              onMouseEnter={(e) => {
                if (!active) e.currentTarget.style.color = "var(--fg)";
              }}
              onMouseLeave={(e) => {
                if (!active) e.currentTarget.style.color = "var(--muted)";
              }}
            >
              {t.label}
            </button>
          );
        })}
        {/* Creative Kit entry (R7-2) */}
        <button
          type="button"
          onClick={onOpenKit}
          title="✨ 灵感套件 — 一键生成世界观/人物/主线"
          className="flex-1 py-sp-2 text-center transition-colors"
          style={{
            color: kitOpen ? "var(--accent)" : "var(--muted)",
            fontSize: "13px",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "var(--fg)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "var(--muted)";
          }}
        >
          ✨
        </button>
      </div>
      {/* Tab body */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {leftTab === "outline" && (
          <div className="h-full overflow-y-auto">
            <OutlinePanel
              chapters={chapters}
              activeChapterId={activeChapterId}
              loading={chaptersLoading}
              outline={outline}
              onSaveOutline={onSaveOutline}
              onExtractEntities={onExtractEntities}
              extracting={extracting}
              onSelect={(id) => onSelectChapter(id)}
              onAdd={onAddChapter}
              onDelete={onDeleteChapter}
              onRename={onRenameChapter}
              onReorder={onReorder}
              onContinueChapter={onContinueChapter}
              onAiPolish={onOutlinePolish}
            />          </div>
        )}
        {leftTab === "characters" && (
          <div key={panelRefreshKey} className="h-full overflow-y-auto">
            <CharacterPanel docId={docId} />
          </div>
        )}
        {leftTab === "world" && (
          <div key={panelRefreshKey} className="h-full overflow-y-auto">
            <WorldSettingPanel docId={docId} />
          </div>
        )}
        {leftTab === "events" && (
          <div key={panelRefreshKey} className="h-full overflow-y-auto">
            <PlotEventPanel
              docId={docId}
              chapters={chapters.map((c) => ({
                id: c.id,
                chapter_index: c.chapter_index,
                title: c.title,
              }))}
              onSelectChapter={(chapterId: number) => onSelectChapter(chapterId)}
            />
          </div>
        )}
        {/* R10: relationship graph / timeline DAG / consistency sentinel */}
        {(leftTab === "graph" || leftTab === "timeline") && (
          <div className="h-full overflow-y-auto px-sp-2 py-sp-2 flex flex-col">
            {/* Fullscreen jump — the 200px sidebar is preview-sized; the
                dedicated /novels/[id]/graph page gives the SVG full width. */}
            <button
              type="button"
              onClick={() => onOpenFullscreen(leftTab)}
              className="self-end mb-sp-1 px-sp-2 py-px rounded-sm text-[10px] border transition-colors shrink-0"
              style={{ borderColor: "var(--border-hairline)", color: "var(--fg-secondary)" }}
              title="全屏打开（完整宽度）"
            >
              ⤢ 全屏
            </button>
            {leftTab === "graph" && <RelationshipGraph docId={docId} />}
            {leftTab === "timeline" && <TimelineGraph docId={docId} />}
          </div>
        )}
        {leftTab === "consistency" && (
          <div className="h-full overflow-y-auto">
            <ConsistencyPanel
              docId={docId}
              chapterId={activeChapterId}
              chapterText={currentText}
            />
          </div>
        )}
      </div>
    </div>
  );
}
