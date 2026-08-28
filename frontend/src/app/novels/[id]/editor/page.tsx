"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import Placeholder from "@tiptap/extension-placeholder";
import StarterKit from "@tiptap/starter-kit";
import { useEditor } from "@tiptap/react";
import { EditorContent } from "@tiptap/react";

import { getDocument, updateDocument } from "@/lib/documents";
import { listChapters, createChapter, updateChapter, deleteChapter, reorderChapters } from "@/lib/chapters";
import type { EditorDoc, ChapterListItem, ChapterRead, DocumentPartial, DocumentInput } from "@/lib/types";
import type { SaveState } from "@/hooks/use-documents";

import { WriterSettingsBar, DEFAULT_SETTINGS, type WritingSettings } from "@/components/WriterSettingsBar";
import { WordCountBar } from "@/components/WordCountBar";
import { OutlinePanel } from "@/components/OutlinePanel";
import { CharacterPanel } from "@/components/CharacterPanel";
import { WorldSettingPanel } from "@/components/WorldSettingPanel";
import PlotEventPanel from "@/components/PlotEventPanel";
import { AIToolPanel } from "@/components/AIToolPanel";
import { AssistantPanel } from "@/components/AssistantPanel";
import { FormatToolbar } from "@/components/FormatToolbar";
import {
  DEFAULT_DISPLAY,
  DISPLAY_FONT_SIZES,
  DISPLAY_LINE_HEIGHTS,
  DISPLAY_WIDTHS,
  EditorDisplaySettings,
  loadDisplay,
  saveDisplay,
  type EditorDisplay,
} from "@/components/EditorDisplaySettings";
import { EditorToolbar, FindReplaceBar } from "@/components/EditorToolbar";
import { FocusModeBar } from "@/components/FocusModeBar";
import { CreativeKitDialog } from "@/components/CreativeKitDialog";
import { VersionHistoryDialog } from "@/components/VersionHistoryDialog";
import { matchesShortcut } from "@/lib/shortcuts";
import { createSnapshot } from "@/lib/snapshots";
import { extractEntitiesFromOutline } from "@/lib/extract-entities";
import { createCharacter } from "@/lib/characters";
import { createWorldSetting } from "@/lib/world-settings";
import { createPlotEvent } from "@/lib/plot-events";
import { downloadExport, EXPORT_LABELS, type ExportFormat } from "@/lib/export";
import { fetchSafetyScan, type SafetyScanReport } from "@/lib/safety";
import { SafetyScanDialog } from "@/components/SafetyScanDialog";

function countWords(text: string): number {
  if (!text) return 0;
  const cjk = (text.match(/[一-鿿㐀-䶿豈-﫿]/g) || []).length;
  const latin = text.replace(/[一-鿿㐀-䶿豈-﫿]/g, " ").trim();
  const words = latin ? latin.split(/\s+/).filter(Boolean).length : 0;
  return cjk + words;
}

export default function NovelEditorPage() {
  const params = useParams();
  const router = useRouter();
  const docId = Number(params.id);

  // ── Document state ──────────────────────────────────────────────────
  const [doc, setDoc] = useState<EditorDoc | null>(null);
  const [docLoading, setDocLoading] = useState(true);
  const [docError, setDocError] = useState<string | null>(null);

  // ── Chapter state ───────────────────────────────────────────────────
  const [chapters, setChapters] = useState<ChapterListItem[]>([]);
  const [activeChapter, setActiveChapter] = useState<ChapterRead | null>(null);
  const [chaptersLoading, setChaptersLoading] = useState(true);
  const [activeChapterLoading, setActiveChapterLoading] = useState(false);

  // ── Editor state ────────────────────────────────────────────────────
  const [title, setTitle] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Writing settings ────────────────────────────────────────────────
  const [settings, setSettings] = useState<WritingSettings>(DEFAULT_SETTINGS);

  // ── Toolbar state ───────────────────────────────────────────────────
  const [mobilePreview, setMobilePreview] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light" | "eye-care">(() => {
    if (typeof window === "undefined") return "dark";
    return (localStorage.getItem("project11:theme") as "dark" | "light" | "eye-care") || "dark";
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

  // Export menu state (F3).
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);

  // ── 交稿雷达 (R6-3) state + handlers ─────────────────────────────
  const [radarOpen, setRadarOpen] = useState(false);
  const [radarReport, setRadarReport] = useState<SafetyScanReport | null>(null);
  const [radarLoading, setRadarLoading] = useState(false);
  const [radarError, setRadarError] = useState<string | null>(null);
  const [pendingExportFmt, setPendingExportFmt] = useState<ExportFormat | null>(null);

  const runSafetyScan = useCallback(async () => {
    if (!doc) return;
    setRadarLoading(true);
    setRadarError(null);
    try {
      const report = await fetchSafetyScan(doc.id);
      setRadarReport(report);
    } catch (e) {
      setRadarError(e instanceof Error ? e.message : "安全检查失败");
    } finally {
      setRadarLoading(false);
    }
  }, [doc]);

  const handleOpenRadar = useCallback(() => {
    setPendingExportFmt(null);
    setRadarReport(null);
    setRadarError(null);
    setRadarOpen(true);
    void runSafetyScan();
  }, [runSafetyScan]);

  const handleContinueExport = useCallback(async () => {
    if (!doc || !pendingExportFmt) return;
    try {
      await downloadExport(doc.id, pendingExportFmt);
    } catch (e) {
      alert(`❌ 导出失败: ${e instanceof Error ? e.message : "未知错误"}`);
    } finally {
      setPendingExportFmt(null);
      setRadarOpen(false);
    }
  }, [doc, pendingExportFmt]);

  const radarStatus: "idle" | "scanning" | "clean" | "warn" = radarLoading
    ? "scanning"
    : radarReport
      ? radarReport.findings.length > 0
        ? "warn"
        : "clean"
      : "idle";

  // Right panel tab: AI 工具 (AIToolPanel) / AI 编剧 (AssistantPanel, F1).
  const [rightTab, setRightTab] = useState<"tools" | "assistant">("tools");
  const [findOpen, setFindOpen] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  const [kitOpen, setKitOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedText, setSelectedText] = useState("");
  const [extracting, setExtracting] = useState(false);

  // ── Left sidebar tab state ─────────────────────────────────────────
  const [leftTab, setLeftTab] = useState<"outline"|"characters"|"world"|"events">("outline");
  // Incrementing this key forces panel components to remount and re-fetch after extraction.
  const [panelRefreshKey, setPanelRefreshKey] = useState(0);

  // ── Find & replace state ──────────────────────────────────────────────
  const [findMatches, setFindMatches] = useState<Array<{ from: number; to: number }>>([]);
  const [findIndex, setFindIndex] = useState(-1);
  const findQueryRef = useRef<string>("");

  // Apply theme to <html> and persist to localStorage.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("project11:theme", theme);
  }, [theme]);

  // Load document.
  useEffect(() => {
    if (!docId || isNaN(docId)) return;
    (async () => {
      setDocLoading(true);
      try {
        const d = await getDocument(docId);
        setDoc(d);
        setTitle(d.title);
        // Restore writing settings from metadata_json.
        const meta = (d.metadata_json ?? {}) as Record<string, unknown>;
        if (meta.writing_type || meta.pov || meta.genre) {
          setSettings({
            writing_type: (meta.writing_type as string) ?? "长篇",
            pov: (meta.pov as string) ?? "第三人称",
            genre: (meta.genre as string) ?? "全频",
          });
        }
      } catch (e) {
        setDocError(e instanceof Error ? e.message : "加载失败");
      } finally {
        setDocLoading(false);
      }
    })();
  }, [docId]);

  // Load chapters.
  const refreshChapters = useCallback(async () => {
    setChaptersLoading(true);
    try {
      const r = await listChapters(docId);
      setChapters(r.items);
    } catch {
      // ignore — chapters are optional for a new doc
    } finally {
      setChaptersLoading(false);
    }
  }, [docId]);

  useEffect(() => {
    void refreshChapters();
  }, [refreshChapters]);

  // Tiptap editor instance.
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
      }),
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

  // Sync editor content from active chapter.
  useEffect(() => {
    if (!editor) return;
    const html = activeChapter?.content_text ?? "";
    editor.chain().setContent(html, false).setMeta("addToHistory", false).run();
    setDirty(false);
  }, [editor, activeChapter]);

  // Track dirty state.
  useEffect(() => {
    if (!editor) return;
    const handler = () => setDirty(true);
    editor.on("update", handler);
    return () => { editor.off("update", handler); };
  }, [editor]);

  // Prevent unload with unsaved changes.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty) { e.preventDefault(); e.returnValue = ""; }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  // Track editor selection for AI tools
  useEffect(() => {
    if (!editor) return;
    const handler = () => {
      const { from, to } = editor.state.selection;
      if (from !== to) {
        const selected = editor.state.doc.textBetween(from, to, "");
        setSelectedText(selected);
      } else {
        setSelectedText("");
      }
    };
    editor.on("selectionUpdate", handler);
    return () => { editor.off("selectionUpdate", handler); };
  }, [editor]);

  // Ctrl+Shift+F for focus mode.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (matchesShortcut(e, "Ctrl+Shift+F")) {
        e.preventDefault();
        setFocusMode((p) => !p);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Ctrl+H for find & replace.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "h") {
        e.preventDefault();
        setFindOpen((p) => !p);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // ── Save logic ──────────────────────────────────────────────────────

  const performSave = useCallback(async () => {
    if (!editor || !doc) return;
    setSaveState("saving");
    try {
      const text = editor.getText();
      // Save current chapter content.
      if (activeChapter) {
        const wordCount = countWords(text);
        await updateChapter(docId, activeChapter.id, {
          content_text: text,
        });
        // Refresh chapter list to update word count in the outline.
        void refreshChapters();
      }
      // Update the document title and writing settings.
      // PATCH-merge only the changed settings keys with merge_metadata, so an
      // outline written by Creative Kit (or another tab) is never clobbered by
      // this save's possibly-stale copy of the whole metadata_json.
      const body: DocumentPartial = {
        title: title.trim() || "未命名",
        metadata_json: { ...(settings as unknown as Record<string, unknown>) },
        merge_metadata: true,
      };
      const updated = await updateDocument(docId, body);
      setDoc(updated);
      setDirty(false);
      setSaveState("saved");
      // Create a server-side snapshot for history (best-effort).
      if (activeChapter) {
        try {
          await createSnapshot(docId, activeChapter.id, editor.getText(), {
            title: activeChapter.title,
            reason: "save",
          });
        } catch {
          // A failed snapshot must never block the save itself.
        }
      }
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => setSaveState("idle"), 1500);
    } catch {
      setSaveState("error");
    }
  }, [editor, doc, activeChapter, title, settings, docId, refreshChapters]);

  const handleAutoSave = useCallback(() => {
    if (dirty) void performSave();
  }, [dirty, performSave]);

  const handleSave = useCallback(() => {
    if (dirty) void performSave();
  }, [dirty, performSave]);

  // R7-1 focus-mode shortcut suite: Ctrl+S save, Ctrl+\ focus toggle,
  // Ctrl+F find, Ctrl+Enter continue-writing entry (surface AI tools).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (matchesShortcut(e, "Ctrl+S")) {
        e.preventDefault();
        if (dirty) void performSave();
        return;
      }
      if (matchesShortcut(e, "Ctrl+\\")) {
        e.preventDefault();
        setFocusMode((p) => !p);
        return;
      }
      if (matchesShortcut(e, "Ctrl+F")) {
        e.preventDefault();
        setFindOpen((p) => !p);
        return;
      }
      if (matchesShortcut(e, "Ctrl+Enter")) {
        e.preventDefault();
        // The AI tool panel is hidden in focus mode; exit it so the user can
        // reach the continue-writing entry (matches the bar's hint text).
        setFocusMode(false);
        setRightTab("tools");
        return;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [dirty, performSave]);

  // Cleanup timeout.
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  // ── Find & replace logic ──────────────────────────────────────────────

  const buildMatchList = useCallback(
    (query: string): Array<{ from: number; to: number }> => {
      if (!editor || !query) return [];
      const doc = editor.state.doc;
      const matches: Array<{ from: number; to: number }> = [];
      const lowerQuery = query.toLowerCase();

      doc.descendants((node, pos) => {
        if (!node.isText || !node.text) return;
        const nodeText = node.text;
        let searchFrom = 0;
        while (searchFrom < nodeText.length) {
          const idx = nodeText.toLowerCase().indexOf(lowerQuery, searchFrom);
          if (idx === -1) break;
          const from = pos + idx;
          const to = pos + idx + query.length;
          matches.push({ from, to });
          searchFrom = idx + 1;
        }
      });

      return matches;
    },
    [editor],
  );

  const handleFind = useCallback(
    (query: string) => {
      findQueryRef.current = query;
      if (!editor || !query) {
        setFindMatches([]);
        setFindIndex(-1);
        return;
      }
      const matches = buildMatchList(query);
      setFindMatches(matches);
      if (matches.length > 0) {
        setFindIndex(0);
        // Select first match.
        const m = matches[0];
        editor.chain().focus().setTextSelection({ from: m.from, to: m.to }).run();
      } else {
        setFindIndex(-1);
      }
    },
    [editor, buildMatchList],
  );

  const handleFindNext = useCallback(() => {
    if (findMatches.length === 0) return;
    const next = (findIndex + 1) % findMatches.length;
    setFindIndex(next);
    const m = findMatches[next];
    editor?.chain().focus().setTextSelection({ from: m.from, to: m.to }).run();
  }, [editor, findMatches, findIndex]);

  const handleFindPrev = useCallback(() => {
    if (findMatches.length === 0) return;
    const prev = findIndex <= 0 ? findMatches.length - 1 : findIndex - 1;
    setFindIndex(prev);
    const m = findMatches[prev];
    editor?.chain().focus().setTextSelection({ from: m.from, to: m.to }).run();
  }, [editor, findMatches, findIndex]);

  const handleReplace = useCallback(
    (query: string, replacement: string) => {
      if (!editor || findMatches.length === 0 || findIndex < 0) return;
      const m = findMatches[findIndex];
      editor
        .chain()
        .focus()
        .deleteRange({ from: m.from, to: m.to })
        .insertContentAt(m.from, replacement)
        .run();
      // Rebuild matches after replace.
      const newMatches = buildMatchList(query);
      setFindMatches(newMatches);
      // Keep index at same position (now points to next match or wraps).
      const newIdx = Math.min(findIndex, newMatches.length - 1);
      setFindIndex(newIdx);
      if (newMatches.length > 0 && newIdx >= 0) {
        const nm = newMatches[newIdx];
        editor.chain().focus().setTextSelection({ from: nm.from, to: nm.to }).run();
      }
    },
    [editor, findMatches, findIndex, buildMatchList],
  );

  const handleReplaceAll = useCallback(
    (query: string, replacement: string) => {
      if (!editor || !query) return;
      // Replace from end to start to preserve positions.
      const matches = buildMatchList(query);
      for (let i = matches.length - 1; i >= 0; i--) {
        const m = matches[i];
        editor
          .chain()
          .deleteRange({ from: m.from, to: m.to })
          .insertContentAt(m.from, replacement)
          .run();
      }
      setFindMatches([]);
      setFindIndex(-1);
    },
    [editor, buildMatchList],
  );

  const matchDisplay = useMemo(() => {
    if (findMatches.length === 0) return null;
    return `${findIndex + 1} / ${findMatches.length}`;
  }, [findMatches, findIndex]);

  // ── Chapter handlers ────────────────────────────────────────────────

  const handleAddChapter = useCallback(async () => {
    try {
      // Next index = max existing + 1, NOT chapters.length — the outline
      // auto-create can leave world-setting rows occupying early indices,
      // so length over-counts and jumps past the real next chapter.
      const nextIndex =
        chapters.reduce((m, c) => Math.max(m, c.chapter_index ?? 0), -1) + 1;
      const ch = await createChapter(docId, {
        chapter_index: nextIndex,
        title: `第${nextIndex + 1}章`,
      });
      setChapters((prev) => [...prev, ch]);
      setActiveChapter({
        ...ch,
        novel_id: docId,
        content_text: "",
        summary: "",
        metadata_json: {},
        created_at: ch.updated_at,
      });
      if (editor) editor.commands.clearContent();
      setDirty(false);
    } catch (e) {
      alert(e instanceof Error ? e.message : "创建章节失败");
    }
  }, [docId, chapters, editor]);

  const handleSelectChapter = useCallback(async (chapterId: number) => {
    // Save current chapter first if dirty.
    if (dirty) await performSave();
    setActiveChapterLoading(true);
    try {
      // The backend list endpoint returns full Chapter objects, so
      // content_text is available in the ChapterListItem.
      const r = await listChapters(docId, 500);
      const found = r.items.find((c) => c.id === chapterId);
      if (found) {
        setActiveChapter({
          ...found,
          novel_id: docId,
          content_text: found.content_text ?? "",
          summary: "",
          metadata_json: {},
          created_at: found.updated_at,
        });
      }
    } catch {
      // ignore
    } finally {
      setActiveChapterLoading(false);
    }
  }, [docId, dirty, performSave]);

  const handleDeleteChapter = useCallback(async (chapterId: number) => {
    if (!window.confirm("删除此章节？")) return;
    try {
      await deleteChapter(docId, chapterId);
      setChapters((prev) => prev.filter((c) => c.id !== chapterId));
      if (activeChapter?.id === chapterId) {
        setActiveChapter(null);
        if (editor) editor.commands.clearContent();
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "删除章节失败");
    }
  }, [docId, activeChapter, editor]);

  const handleRenameChapter = useCallback(async (chapterId: number, newTitle: string) => {
    try {
      const updated = await updateChapter(docId, chapterId, { title: newTitle });
      setChapters((prev) =>
        prev.map((c) => (c.id === chapterId ? { ...c, title: updated.title } : c))
      );
      if (activeChapter?.id === chapterId) {
        setActiveChapter((p) => p ? { ...p, title: updated.title } : null);
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "重命名失败");
    }
  }, [docId, activeChapter]);

  const handleReorder = useCallback(async (orderedIds: Array<{ id: number; chapter_index: number }>) => {
    try {
      const r = await reorderChapters(docId, orderedIds);
      setChapters(r.items);
    } catch (e) {
      alert(e instanceof Error ? e.message : "排序失败");
    }
  }, [docId]);

  // ── Insert AI text ──────────────────────────────────────────────────

  const handleInsertIntoEditor = useCallback(
    async (text: string) => {
      // Auto-snapshot before any AI insertion so the author can roll back.
      if (activeChapter) {
        try {
          await createSnapshot(docId, activeChapter.id, editor?.getText() ?? "", {
            title: activeChapter.title,
            reason: "insert",
          });
        } catch {
          // Best-effort; never block the insertion on a failed snapshot.
        }
      }
      editor?.chain().focus().insertContent(text).run();
    },
    [editor, docId, activeChapter],
  );

  const handleReplaceInEditor = useCallback(
    async (text: string) => {
      if (!editor) return;
      // Auto-snapshot before an AI replace so the previous text is restorable.
      if (activeChapter) {
        try {
          await createSnapshot(docId, activeChapter.id, editor.getText(), {
            title: activeChapter.title,
            reason: "replace",
          });
        } catch {
          // Best-effort; never block the replace on a failed snapshot.
        }
      }
      const { from, to } = editor.state.selection;
      if (from !== to) {
        editor.chain().focus().deleteRange({ from, to }).insertContentAt(from, text).run();
      } else {
        editor.chain().focus().insertContent(text).run();
      }
    },
    [editor, docId, activeChapter],
  );

  const handleApplyOutline = useCallback(
    async (outlineText: string) => {
      if (!doc) return;
      try {
        // Save outline to document metadata. Send ONLY the changed keys —
        // the server PATCH-merges under a row lock, so a concurrent write to
        // a different metadata key (e.g. settings) is never clobbered by a
        // stale full-copy being replayed. Local state still merges in place.
        await updateDocument(docId, {
          metadata_json: {
            outline: outlineText,
            outline_updated_at: new Date().toISOString(),
          },
          merge_metadata: true,
        });
        setDoc({
          ...doc,
          metadata_json: {
            ...(doc.metadata_json ?? {}),
            outline: outlineText,
            outline_updated_at: new Date().toISOString(),
          },
        });

        // Auto-create chapters from outline if none exist.
        // Also extract per-chapter summaries from the text between chapter headings.
        if (chapters.length === 0) {
          const lines = outlineText.split("\n");
          // Find chapter heading lines and their indices.
          const chapterEntries: Array<{ idx: number; title: string }> = [];
          for (let i = 0; i < lines.length; i++) {
            const trimmed = lines[i].trim();
            if (
              /^第[一二三四五六七八九十百千\d]+章/.test(trimmed)
            ) {
              const title =
                trimmed.replace(/^\d+[\.\、]\s*/, "").trim().slice(0, 50) ||
                `第${chapterEntries.length + 1}章`;
              chapterEntries.push({ idx: i, title });
            }
          }

          if (chapterEntries.length > 0) {
            for (let i = 0; i < chapterEntries.length; i++) {
              const start = chapterEntries[i].idx + 1;
              const end =
                i + 1 < chapterEntries.length
                  ? chapterEntries[i + 1].idx
                  : lines.length;
              // Collect non-empty lines between this heading and the next as summary.
              const summaryLines = lines
                .slice(start, end)
                .filter((l) => l.trim());
              const summary = summaryLines.join("\n").trim().slice(0, 500);
              await createChapter(docId, {
                chapter_index: i,
                title: chapterEntries[i].title,
                ...(summary ? { summary } : {}),
              });
            }
            void refreshChapters();
          }
        }

        // Auto-extract characters/world/events from outline.
        try {
          setExtracting(true);
          const entities = await extractEntitiesFromOutline(outlineText);

          // allSettled so one failed item doesn't abort the rest.
          const [charResults, wsResults, peResults] = await Promise.all([
            Promise.allSettled(
              entities.characters.map((ch) =>
                createCharacter(docId, {
                  name: ch.name,
                  role: ch.role || "其他",
                  description: ch.description || "",
                  arc_summary: ch.arc_summary || "",
                }),
              ),
            ),
            Promise.allSettled(
              entities.world_settings.map((ws) =>
                createWorldSetting(docId, {
                  category: ws.category || "其他",
                  title: ws.title,
                  content_text: ws.content_text || "",
                }),
              ),
            ),
            Promise.allSettled(
              entities.plot_events.map((pe) =>
                createPlotEvent(docId, {
                  summary: pe.summary,
                  event_type: pe.event_type || "其他",
                  chapter_index: pe.chapter_index ?? null,
                }),
              ),
            ),
          ]);
          const charOk = charResults.filter((r) => r.status === "fulfilled").length;
          const wsOk   = wsResults.filter((r) => r.status === "fulfilled").length;
          const peOk   = peResults.filter((r) => r.status === "fulfilled").length;

          // Force panels to remount and re-fetch.
          setPanelRefreshKey((k) => k + 1);
          if (entities.characters.length > 0) {
            setLeftTab("characters");
          }
          alert(
            `✅ 大纲已保存，已提取 ${charOk} 个角色、${wsOk} 个设定、${peOk} 个事件`,
          );
        } catch (extractErr) {
          const msg =
            extractErr instanceof Error ? extractErr.message : "提取失败";
          alert(
            `✅ 大纲已保存（自动提取失败：${msg}，可手动点 AI 提取）\n\n提示：请先在设置中测试 API 连接是否正常`,
          );
        } finally {
          setExtracting(false);
        }
      } catch (e) {
        alert(e instanceof Error ? e.message : "保存大纲失败");
      }
    },
    [doc, docId, chapters, refreshChapters, setPanelRefreshKey],
  );

  const handleSaveOutline = useCallback(
    async (text: string) => {
      if (!doc) return;
      try {
        // Same send-only-changed-keys contract as handleApplyOutline above.
        await updateDocument(docId, {
          metadata_json: {
            outline: text,
            outline_updated_at: new Date().toISOString(),
          },
          merge_metadata: true,
        });
        setDoc({
          ...doc,
          metadata_json: {
            ...(doc.metadata_json ?? {}),
            outline: text,
            outline_updated_at: new Date().toISOString(),
          },
        });
      } catch (e) {
        alert(e instanceof Error ? e.message : "保存大纲失败");
      }
    },
    [doc, docId],
  );

  const handleExtractEntities = useCallback(async () => {
    const outlineText = (doc?.metadata_json as Record<string, unknown> | undefined)?.outline as string | undefined;
    if (!outlineText) {
      alert("请先生成或编写大纲");
      return;
    }
    setExtracting(true);
    try {
      const entities = await extractEntitiesFromOutline(outlineText);

      // Use allSettled so a single failed item doesn't abort the rest.
      const charResults = await Promise.allSettled(
        entities.characters.map((ch) =>
          createCharacter(docId, {
            name: ch.name,
            role: ch.role || "其他",
            description: ch.description || "",
            arc_summary: ch.arc_summary || "",
          }),
        ),
      );
      const wsResults = await Promise.allSettled(
        entities.world_settings.map((ws) =>
          createWorldSetting(docId, {
            category: ws.category || "其他",
            title: ws.title,
            content_text: ws.content_text || "",
          }),
        ),
      );
      const peResults = await Promise.allSettled(
        entities.plot_events.map((pe) =>
          createPlotEvent(docId, {
            summary: pe.summary,
            event_type: pe.event_type || "其他",
            chapter_index: pe.chapter_index ?? null,
          }),
        ),
      );

      const charOk = charResults.filter((r) => r.status === "fulfilled").length;
      const wsOk   = wsResults.filter((r) => r.status === "fulfilled").length;
      const peOk   = peResults.filter((r) => r.status === "fulfilled").length;
      const failed = [charResults, wsResults, peResults]
        .flat()
        .filter((r) => r.status === "rejected").length;

      // Force all panels to remount so they re-fetch fresh data regardless of
      // which tab is currently active (avoids the no-op setLeftTab bug).
      setPanelRefreshKey((k) => k + 1);
      if (entities.characters.length > 0) {
        setLeftTab("characters");
      }

      const summary = `✅ 已从大纲提取：${charOk} 个角色，${wsOk} 个世界观设定，${peOk} 个剧情事件`;
      alert(failed > 0 ? `${summary}\n⚠️ ${failed} 条因校验失败被跳过` : summary);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "提取失败";
      alert(`❌ 提取失败：${msg}\n\n请检查：1) 自定义 API 配置是否正确（设置 → 测试连接）；2) 大纲内容是否完整`);
    } finally {
      setExtracting(false);
    }
  }, [doc, docId, setPanelRefreshKey]);

  // ── Computed values ─────────────────────────────────────────────────

  const currentText = editor?.getText() ?? "";
  const chapterWordCount = useMemo(() => countWords(currentText), [currentText]);
  const totalWordCount = useMemo(
    () => chapters.reduce((sum, c) => sum + c.word_count, 0) + (activeChapter ? 0 : 0),
    [chapters, activeChapter],
  );

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
        {/* Left: Tabbed sidebar (Outline / Characters / World / Events) */}
        {!focusMode && (
          <div className="flex flex-col h-full min-h-0" style={{ background: "var(--surface)" }}>
            {/* Tab strip */}
            <div
              className="flex shrink-0 border-b text-[11px]"
              style={{ borderColor: "var(--border-subtle)" }}
            >
              {(
                [
                  { key: "outline" as const, label: "📖", title: "大纲" },
                  { key: "characters" as const, label: "👤", title: "角色" },
                  { key: "world" as const, label: "🌍", title: "世界观" },
                  { key: "events" as const, label: "📋", title: "剧情" },
                ]
              ).map((t) => {
                const active = leftTab === t.key;
                return (
                  <button
                    key={t.key}
                    onClick={() => setLeftTab(t.key)}
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
                onClick={() => setKitOpen(true)}
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
                    activeChapterId={activeChapter?.id ?? null}
                    loading={chaptersLoading}
                    outline={(doc?.metadata_json as Record<string, unknown> | undefined)?.outline as string | undefined}
                    onSaveOutline={(text) => void handleSaveOutline(text)}
                    onExtractEntities={() => void handleExtractEntities()}
                    extracting={extracting}
                    onSelect={(id) => void handleSelectChapter(id)}
                    onAdd={() => void handleAddChapter()}
                    onDelete={(id) => void handleDeleteChapter(id)}
                    onRename={(id, t) => void handleRenameChapter(id, t)}
                    onReorder={(ids) => void handleReorder(ids)}
                    onContinueChapter={(id) => {
                      // R6-1: mind-map continue entry — load the chapter and
                      // surface the AI tools so "续写" is one click away.
                      void handleSelectChapter(id);
                      setRightTab("tools");
                    }}
                  />
                </div>
              )}
              {leftTab === "characters" && (
                <div key={panelRefreshKey} className="h-full overflow-y-auto">
                  <CharacterPanel docId={Number(docId)} />
                </div>
              )}
              {leftTab === "world" && (
                <div key={panelRefreshKey} className="h-full overflow-y-auto">
                  <WorldSettingPanel docId={Number(docId)} />
                </div>
              )}
              {leftTab === "events" && (
                <div key={panelRefreshKey} className="h-full overflow-y-auto">
                  <PlotEventPanel
                    docId={Number(docId)}
                    chapters={chapters.map((c) => ({
                      id: c.id,
                      chapter_index: c.chapter_index,
                      title: c.title,
                    }))}
                    onSelectChapter={(chapterId: number) =>
                      void handleSelectChapter(chapterId)
                    }
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {/* Center: Editor */}
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
          {!activeChapter && !chaptersLoading && chapters.length === 0 && (
            <div className="flex-1 flex flex-col items-center justify-center gap-sp-4" style={{ color: "var(--muted)" }}>
              <svg className="w-14 h-14" style={{ color: "var(--border)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
              <p className="text-[13px]">暂无章节，点击左侧大纲中的「+」开始</p>
            </div>
          )}

          {/* Editor content */}
          {editor && (activeChapter || chapters.length > 0) && (
            <>
              <FormatToolbar editor={editor} />
              <div className="flex-1 overflow-y-auto px-sp-8 py-sp-6 relative" style={{ background: "var(--bg-warm)" }}>
                {/* Export (F3) + display comfort settings (font / line-height / width) */}
                <div className="absolute top-sp-2 right-sp-3 z-20 flex items-center gap-sp-1">
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setExportOpen((v) => !v)}
                      title="导出作品（Markdown / TXT / EPUB）"
                      aria-label="导出作品"
                      aria-expanded={exportOpen}
                      className="w-7 h-7 flex items-center justify-center rounded-sm transition-colors"
                      style={{
                        color: exportOpen ? "var(--accent)" : "var(--muted)",
                        background: exportOpen ? "var(--accent-bg)" : "transparent",
                      }}
                      onMouseEnter={(e) => {
                        if (!exportOpen) {
                          e.currentTarget.style.background = "var(--surface-2)";
                          e.currentTarget.style.color = "var(--fg)";
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (!exportOpen) {
                          e.currentTarget.style.background = "transparent";
                          e.currentTarget.style.color = "var(--muted)";
                        }
                      }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                    </button>
                    {exportOpen && (
                      <>
                        <div className="fixed inset-0 z-30" onClick={() => setExportOpen(false)} />
                        <div
                          className="absolute right-0 top-9 z-40 py-sp-1 rounded-md border shadow-lg min-w-[140px]"
                          style={{ background: "var(--surface)", borderColor: "var(--border-hairline)" }}
                        >
                          {(Object.keys(EXPORT_LABELS) as ExportFormat[]).map((fmt) => (
                            <button
                              key={fmt}
                              type="button"
                              disabled={exporting !== null}
                              onClick={async () => {
                                if (!doc) return;
                                setExporting(fmt);
                                try {
                                  // Auto-snapshot before exporting so the
                                  // current draft is recoverable.
                                  if (activeChapter) {
                                    try {
                                      await createSnapshot(docId, activeChapter.id, currentText, {
                                        title: activeChapter.title,
                                        reason: "export",
                                      });
                                    } catch {
                                      // Best-effort; never block the export.
                                    }
                                  }
                                  // 交稿雷达 (R6-3)：导出前自动预检，提示可忽略，不阻塞导出。
                                  const preflight = await fetchSafetyScan(doc.id).catch(() => null);
                                  if (preflight && preflight.findings.length > 0) {
                                    setPendingExportFmt(fmt);
                                    setRadarReport(preflight);
                                    setRadarOpen(true);
                                    return;
                                  }
                                  await downloadExport(doc.id, fmt);
                                } catch (e) {
                                  alert(`❌ 导出失败: ${e instanceof Error ? e.message : "未知错误"}`);
                                } finally {
                                  setExporting(null);
                                  setExportOpen(false);
                                }
                              }}
                              className="w-full px-sp-3 py-sp-1.5 flex items-center justify-between gap-sp-2 text-[12px] font-medium transition-colors disabled:opacity-40"
                              style={{ color: "var(--fg-secondary)" }}
                              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--surface-2)"; }}
                              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                            >
                              <span>{EXPORT_LABELS[fmt]}</span>
                              {exporting === fmt && (
                                <span className="w-[4px] h-[4px] rounded-full" style={{ background: "var(--accent)", animation: "pulse 1.2s infinite" }} />
                              )}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                  <EditorDisplaySettings display={display} onChange={setDisplay} />
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

          {/* Find & replace bar */}
          {findOpen && (
            <FindReplaceBar
              onFind={handleFind}
              onReplace={handleReplace}
              onReplaceAll={handleReplaceAll}
              onFindNext={handleFindNext}
              onFindPrev={handleFindPrev}
              onClose={() => setFindOpen(false)}
              matchDisplay={matchDisplay}
            />
          )}

          {/* Bottom toolbar */}
          <EditorToolbar
            mobilePreview={mobilePreview}
            onToggleMobilePreview={() => setMobilePreview((v) => !v)}
            theme={theme}
            onThemeChange={setTheme}
            findOpen={findOpen}
            onToggleFind={() => setFindOpen((v) => !v)}
            focusActive={focusMode}
            onToggleFocus={() => setFocusMode((v) => !v)}
            onOpenHistory={() => setHistoryOpen(true)}
            onOpenRadar={handleOpenRadar}
            radarStatus={radarStatus}
          />
        </section>

        {/* Right: AI tools / AI assistant */}
        {!focusMode && (
          <div className="flex flex-col h-full min-h-0" style={{ background: "var(--bg)" }}>
            {/* Tab switch */}
            <div
              className="flex shrink-0 border-b text-[11px]"
              style={{ borderColor: "var(--border-subtle)" }}
            >
              {(
                [
                  { key: "tools" as const, label: "AI 工具", title: "写作工具" },
                  { key: "assistant" as const, label: "AI 编剧", title: "对话助手" },
                ]
              ).map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setRightTab(t.key)}
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
                  onInsertIntoEditor={handleInsertIntoEditor}
                  onReplaceInEditor={handleReplaceInEditor}
                  onApplyOutline={handleApplyOutline}
                  editorText={currentText}
                  selectedText={selectedText}
                  chapterTitle={activeChapter?.title ?? ""}
                  chapterIndex={activeChapter?.chapter_index}
                  novelId={docId}
                  novelTitle={title}
                  outlineText={((doc?.metadata_json as Record<string, unknown> | undefined)?.outline as string) ?? ""}
                />
              ) : (
                <AssistantPanel
                  onInsertIntoEditor={handleInsertIntoEditor}
                  activeChapterId={activeChapter?.id ?? null}
                  novelId={docId}
                  chapterTitle={activeChapter?.title ?? ""}
                />
              )}
            </div>
          </div>
        )}
      </div>

      {/* 交稿雷达 (R6-3) dialog */}
      <SafetyScanDialog
        open={radarOpen}
        report={radarReport}
        loading={radarLoading}
        error={radarError}
        pendingExport={pendingExportFmt}
        onClose={() => {
          setPendingExportFmt(null);
          setRadarOpen(false);
        }}
        onContinueExport={handleContinueExport}
        onRescan={runSafetyScan}
      />

      {/* Version history dialog */}
      <VersionHistoryDialog
        open={historyOpen}
        docId={docId}
        chapterId={activeChapter?.id ?? null}
        chapterTitle={activeChapter?.title ?? ""}
        currentText={currentText}
        onClose={() => setHistoryOpen(false)}
        onRestore={(text) => {
          if (editor) {
            editor.chain().setContent(text, false).run();
            setDirty(true);
          }
        }}
      />

      {/* Creative Kit dialog (R7-2) */}
      <CreativeKitDialog
        docId={docId}
        open={kitOpen}
        onClose={() => setKitOpen(false)}
        onApplied={(updated) => {
          // Refresh the parent document copy so a later save never overwrites
          // the applied outline with stale metadata_json (P0 fix).
          setDoc(updated);
          setPanelRefreshKey((k) => k + 1);
        }}
      />
    </div>
  );
}
