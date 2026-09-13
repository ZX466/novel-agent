"use client";

/**
 * Right sidebar: AI 工具 / AI 编剧 tab switch with the matching panel body
 * (AIToolPanel = six writing tools + StageProgress; AssistantPanel = chat).
 */
import { AIToolPanel } from "@/components/AIToolPanel";
import { AssistantPanel } from "@/components/AssistantPanel";

export type RightTab = "tools" | "assistant";

const TABS: Array<{ key: RightTab; label: string; title: string }> = [
  { key: "tools", label: "AI 工具", title: "写作工具" },
  { key: "assistant", label: "AI 编剧", title: "对话助手" },
];

interface RightPanelProps {
  rightTab: RightTab;
  onTabChange: (tab: RightTab) => void;
  onInsertIntoEditor: (text: string) => void;
  onReplaceInEditor: (text: string) => void;
  onApplyOutline: (outlineText: string) => void;
  editorText: string;
  selectedText: string;
  chapterTitle: string;
  chapterIndex: number | undefined;
  novelId: number;
  novelTitle: string;
  outlineText: string;
  activeChapterId: number | null;
  /** R10-⑨ writing settings from the WriterSettingsBar — passed through to
   *  AIToolPanel so every generation request carries 篇幅/视角/频道. */
  writingSettings?: { writing_type: string; pov: string; genre: string };
}

export function RightPanel(props: RightPanelProps) {
  const {
    rightTab, onTabChange, onInsertIntoEditor, onReplaceInEditor,
    onApplyOutline, editorText, selectedText, chapterTitle, chapterIndex,
    novelId, novelTitle, outlineText, activeChapterId,
  } = props;

  return (
    <div className="flex flex-col h-full min-h-0" style={{ background: "var(--bg)" }}>
      {/* Tab switch */}
      <div
        className="flex shrink-0 border-b text-[11px]"
        style={{ borderColor: "var(--border-subtle)" }}
      >
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => onTabChange(t.key)}
            title={t.title}
            className="flex-1 py-sp-2 text-center transition-colors"
            style={{
              color: rightTab === t.key ? "var(--accent)" : "var(--muted)",
              borderBottom: rightTab === t.key ? "2px solid var(--accent)" : "2px solid transparent",
              background: rightTab === t.key ? "var(--bg)" : "transparent",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      {/* Panel body */}
      <div className="flex-1 min-h-0">
        {rightTab === "tools" ? (
          <AIToolPanel
            onInsertIntoEditor={onInsertIntoEditor}
            onReplaceInEditor={onReplaceInEditor}
            onApplyOutline={onApplyOutline}
            editorText={editorText}
            selectedText={selectedText}
            chapterTitle={chapterTitle}
            chapterIndex={chapterIndex}
            novelId={novelId}
            novelTitle={novelTitle}
            outlineText={outlineText}
            writingSettings={props.writingSettings}
          />
        ) : (
          <AssistantPanel
            onInsertIntoEditor={onInsertIntoEditor}
            activeChapterId={activeChapterId}
            novelId={novelId}
            chapterTitle={chapterTitle}
          />
        )}
      </div>
    </div>
  );
}
