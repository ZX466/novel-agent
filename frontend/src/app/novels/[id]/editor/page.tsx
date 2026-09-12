"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import Placeholder from "@tiptap/extension-placeholder";
import StarterKit from "@tiptap/starter-kit";
import { useEditor } from "@tiptap/react";
import { AIParagraph } from "@/components/extensions/AIParagraph";

import { textToParagraphNodes } from "@/lib/insert-text";
import type { EditorDoc, ChapterRead } from "@/lib/types";

import { WriterSettingsBar, type WritingSettings } from "@/components/WriterSettingsBar";
import { WordCountBar } from "@/components/WordCountBar";
import { countWords, useEditorSave } from "@/hooks/use-editor-save";
import { useEditorData } from "@/hooks/use-editor-data";
import { useChapterManager } from "@/hooks/use-chapter-manager";
import { useOutlineWorkflows } from "@/hooks/use-outline-workflows";
import { useEditorInsertion } from "@/hooks/use-editor-insertion";
import { useEditorSync } from "@/hooks/use-editor-sync";
import { useFindReplace } from "@/hooks/use-find-replace";
import { useSafetyRadar } from "@/hooks/use-safety-radar";
import {
  DEFAULT_DISPLAY,
  loadDisplay,
  saveDisplay,
  type EditorDisplay,
} from "@/components/EditorDisplaySettings";
import { EditorToolbar, FindReplaceBar } from "@/components/EditorToolbar";
import { FocusModeBar } from "@/components/FocusModeBar";
import { LeftSidebar, type LeftTab } from "@/components/editor/LeftSidebar";
import { RightPanel, type RightTab } from "@/components/editor/RightPanel";
import { EditorCenter } from "@/components/editor/EditorCenter";
import { EditorDialogs } from "@/components/editor/EditorDialogs";

export default function NovelEditorPage() {
  const params = useParams();
  const router = useRouter();
  const docId = Number(params.id);

  // ── Document / chapters / writing settings (loading hook) ───────────
  const {
    doc, setDoc, docLoading, docError,
    title, setTitle, settings, setSettings,
    chapters, setChapters, chaptersLoading, refreshChapters,
  } = useEditorData(docId);

  // ── Editor state ────────────────────────────────────────────────────
  const [dirty, setDirty] = useState(false);
  const [activeChapter, setActiveChapter] = useState<ChapterRead | null>(null);

  // ── Toolbar state ───────────────────────────────────────────────────
  const [mobilePreview, setMobilePreview] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light" | "eye-care">(() => {
    if (typeof window === "undefined") return "dark";
    return (localStorage.getItem("novel-agent:theme") as "dark" | "light" | "eye-care") || "dark";
  });
  // Editor display comfort settings (font size / line height / width).
  // Deterministic default for SSR; the stored value is loaded after mount.
  const [display, setDisplay] = useState<EditorDisplay>(DEFAULT_DISPLAY);
  useEffect(() => {
    setDisplay(loadDisplay());
  }, []);
  useEffect(() => {
    saveDisplay(display);
  }, [display]);

  // ── 交稿雷达 (R6-3) dialog state + handlers ─────────────────────
  const {
    radarOpen, radarReport, radarLoading, radarError, pendingExportFmt,
    radarStatus, runSafetyScan, handleOpenRadar, handleRadarPreflight,
    handleContinueExport, closeRadar,
  } = useSafetyRadar({ docId: doc?.id ?? null });

  // Right panel tab: AI 工具 (AIToolPanel) / AI 编剧 (AssistantPanel, F1).
  const [rightTab, setRightTab] = useState<RightTab>("tools");
  const [findOpen, setFindOpen] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  const [kitOpen, setKitOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedText, setSelectedText] = useState("");

  // ── Left sidebar tab state ─────────────────────────────────────────
  const [leftTab, setLeftTab] = useState<LeftTab>("outline");
  // Incrementing this key forces panel components to remount and re-fetch after extraction.
  const [panelRefreshKey, setPanelRefreshKey] = useState(0);

  // Apply theme to <html> and persist to localStorage.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("novel-agent:theme", theme);
  }, [theme]);

  // Tiptap editor instance.
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        paragraph: false, // replaced by AIParagraph (persists the ai class)
      }),
      AIParagraph,
      Placeholder.configure({
        placeholder: "开始写作…",
      }),
    ],
    content: "",
    editorProps: {
      attributes: {
        class: "editor-prose",
      },
    },
  });

  // ── Editor sync effects (dirty/selection/unload/shortcuts) ──────────
  useEditorSync({
    editor,
    activeChapter,
    dirty,
    setDirty,
    onSelectionChange: setSelectedText,
    onToggleFocusMode: useCallback(() => setFocusMode((p) => !p), []),
    onToggleFind: useCallback(() => setFindOpen((p) => !p), []),
    onContinueWriting: useCallback(() => {
      setFocusMode(false);
      setRightTab("tools");
    }, []),
  });

  // ── Save logic (extracted hook) ─────────────────────────────────────

  const handleDocSaved = useCallback((updated: EditorDoc) => {
    setDoc(updated);
  }, [setDoc]);

  const { saveState, performSave, handleSave, handleAutoSave } = useEditorSave({
    docId,
    doc,
    editor,
    activeChapterId: activeChapter?.id ?? null,
    activeChapterTitle: activeChapter?.title ?? null,
    title,
    settings,
    dirty,
    onSaved: handleDocSaved,
    onClean: useCallback(() => setDirty(false), []),
    refreshChapters: () => void refreshChapters(),
  });

  // ── Chapter CRUD (extracted hook) ───────────────────────────────────
  const {
    activeChapterLoading,
    handleAddChapter, handleSelectChapter, handleDeleteChapter,
    handleRenameChapter, handleReorder,
  } = useChapterManager({
    docId,
    editor,
    chapters,
    setChapters,
    activeChapter,
    setActiveChapter,
    dirty,
    performSave,
  });

  // ── Outline workflows (extracted hook) ──────────────────────────────
  const { extracting, handleApplyOutline, handleSaveOutline, handleExtractEntities } =
    useOutlineWorkflows({
      doc,
      setDoc,
      docId,
      hasChapters: chapters.length > 0,
      refreshChapters,
      onPanelsMutated: useCallback(() => setPanelRefreshKey((k) => k + 1), []),
      onExtractedCharacters: useCallback(() => setLeftTab("characters"), []),
    });

  // ── AI insertion with snapshots (extracted hook) ────────────────────
  const { handleInsertIntoEditor, handleReplaceInEditor } = useEditorInsertion({
    docId, editor, activeChapter,
  });

  // ── Find & replace logic (extracted hook) ───────────────────────────
  const {
    handleFind, handleFindNext, handleFindPrev,
    handleReplace, handleReplaceAll, matchDisplay,
  } = useFindReplace(editor);

  // ── Computed values ─────────────────────────────────────────────────

  const currentText = editor?.getText() ?? "";
  const chapterWordCount = useMemo(() => countWords(currentText), [currentText]);
  const totalWordCount = useMemo(
    () => chapters.reduce((sum, c) => sum + c.word_count, 0),
    [chapters],
  );

  // Creative Kit applied: refresh the parent document copy so a later save
  // never overwrites the applied outline with stale metadata_json (P0 fix).
  const handleKitApplied = useCallback((updated: EditorDoc) => {
    setDoc(updated);
    setPanelRefreshKey((k) => k + 1);
  }, [setDoc]);

  // ── Loading / error states ──────────────────────────────────────────

  if (docLoading) {
    return (
      <div className="flex items-center justify-center h-full" style={{ background: "var(--bg)" }}>
        <div className="flex flex-col items-center gap-sp-3">
          <svg className="w-8 h-8 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--accent)" }}>
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
          <span className="text-[13px]" style={{ color: "var(--muted)" }}>加载文档中…</span>
        </div>
      </div>
    );
  }

  if (docError || !doc) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-sp-4 p-sp-6" style={{ background: "var(--bg)" }}>
        <p className="text-[14px]" style={{ color: "var(--danger)" }}>{docError || "文档不存在"}</p>
        <button
          type="button"
          onClick={() => router.push("/novels")}
          className="px-sp-4 py-sp-2 rounded-sm text-[12px] font-medium border transition-colors"
          style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
        >
          返回作品列表
        </button>
      </div>
    );
  }

  return (
    <div
      className={`flex flex-col h-full overflow-hidden${focusMode ? " focus-mode-active" : ""}`}
      style={{ background: "var(--bg)" }}
    >
      {/* Top bars */}
      {!focusMode && (
        <>
          <WriterSettingsBar settings={settings} onChange={setSettings} />
          <WordCountBar
            chapterWordCount={chapterWordCount}
            totalWordCount={totalWordCount}
            saveState={saveState}
            dirty={dirty}
            onSave={handleSave}
            onAutoSave={handleAutoSave}
          />
        </>
      )}

      {/* Focus mode slim bar (R7-1): title + save + exit + shortcut hints. */}
      {focusMode && (
        <FocusModeBar
          title={title || "未命名作品"}
          dirty={dirty}
          onSave={handleSave}
          onExit={() => setFocusMode(false)}
        />
      )}

      {/* Three-column body */}
      <div
        className={`flex-1 grid min-h-0${focusMode ? " focus-mode" : ""}`}
        style={{
          gridTemplateColumns: focusMode ? "1fr" : "200px 1fr 220px",
          gap: "1px",
          background: "var(--border-subtle)",
        }}
      >
        {/* Left: Tabbed sidebar */}
        {!focusMode && (
          <LeftSidebar
            leftTab={leftTab}
            onTabChange={setLeftTab}
            panelRefreshKey={panelRefreshKey}
            kitOpen={kitOpen}
            onOpenKit={() => setKitOpen(true)}
            docId={docId}
            chapters={chapters}
            activeChapterId={activeChapter?.id ?? null}
            activeChapterTitle={activeChapter?.title ?? null}
            chaptersLoading={chaptersLoading}
            outline={(doc.metadata_json as Record<string, unknown> | undefined)?.outline as string | undefined}
            extracting={extracting}
            currentText={currentText}
            onSaveOutline={(text) => void handleSaveOutline(text)}
            onExtractEntities={() => void handleExtractEntities()}
            onSelectChapter={(id) => void handleSelectChapter(id)}
            onAddChapter={() => void handleAddChapter()}
            onDeleteChapter={(id) => void handleDeleteChapter(id)}
            onRenameChapter={(id, t) => void handleRenameChapter(id, t)}
            onReorder={(ids) => void handleReorder(ids)}
            onContinueChapter={(id) => {
              // R6-1: mind-map continue entry — load the chapter and
              // surface the AI tools so "续写" is one click away.
              void handleSelectChapter(id);
              setRightTab("tools");
            }}
          />
        )}

        {/* Center: Editor */}
        <EditorCenter
          editor={editor}
          display={display}
          onDisplayChange={setDisplay}
          activeChapter={activeChapter}
          activeChapterLoading={activeChapterLoading}
          hasChapters={chapters.length > 0}
          chaptersLoading={chaptersLoading}
          currentText={currentText}
          docId={docId}
          onRadarPreflight={handleRadarPreflight}
        />

        {/* Right: AI tools / AI assistant */}
        {!focusMode && (
          <RightPanel
            rightTab={rightTab}
            onTabChange={setRightTab}
            onInsertIntoEditor={(text) => void handleInsertIntoEditor(text)}
            onReplaceInEditor={(text) => void handleReplaceInEditor(text)}
            onApplyOutline={(text) => void handleApplyOutline(text)}
            editorText={currentText}
            selectedText={selectedText}
            chapterTitle={activeChapter?.title ?? ""}
            chapterIndex={activeChapter?.chapter_index}
            novelId={docId}
            novelTitle={title}
            outlineText={((doc.metadata_json as Record<string, unknown> | undefined)?.outline as string) ?? ""}
            activeChapterId={activeChapter?.id ?? null}
          />
        )}
      </div>

      {/* Page-level dialogs (radar / history / creative kit) */}
      <EditorDialogs
        docId={docId}
        editor={editor}
        radarOpen={radarOpen}
        radarReport={radarReport}
        radarLoading={radarLoading}
        radarError={radarError}
        pendingExportFmt={pendingExportFmt}
        onCloseRadar={closeRadar}
        onContinueExport={handleContinueExport}
        onRescan={runSafetyScan}
        historyOpen={historyOpen}
        onCloseHistory={() => setHistoryOpen(false)}
        activeChapterId={activeChapter?.id ?? null}
        activeChapterTitle={activeChapter?.title ?? null}
        currentText={currentText}
        kitOpen={kitOpen}
        onCloseKit={() => setKitOpen(false)}
        onKitApplied={handleKitApplied}
      />
    </div>
  );
}
