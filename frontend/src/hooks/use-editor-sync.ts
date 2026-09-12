"use client";

/**
 * Editor-instance side effects: sync active-chapter text into Tiptap (plain
 * text → HTML so paragraphs survive reloads; persisted AI-paragraph markers
 * are re-applied), track dirty state, guard against unload with unsaved
 * changes, surface the selection for AI tools, and the R7-1 shortcut suite
 * (focus mode / find / continue-writing).
 */
import { useEffect } from "react";
import type { Editor as TiptapEditor } from "@tiptap/react";

import { textToTipTapHTML } from "@/lib/insert-text";
import { matchesShortcut } from "@/lib/shortcuts";
import type { ChapterRead } from "@/lib/types";

interface UseEditorSyncOpts {
  editor: TiptapEditor | null;
  activeChapter: ChapterRead | null;
  dirty: boolean;
  setDirty: (v: boolean) => void;
  onSelectionChange: (selected: string) => void;
  // Shortcut actions
  onToggleFocusMode: () => void;
  onToggleFind: () => void;
  onContinueWriting: () => void;
}

/** Re-apply persisted AI-paragraph markers (ai_paragraphs indices) to the
 *  chapter HTML before loading it into the editor. */
function markAiParagraphs(html: string, indices: unknown): string {
  if (!Array.isArray(indices) || indices.length === 0 || !html) return html;
  if (typeof window === "undefined") return html;
  const doc = new DOMParser().parseFromString(html, "text/html");
  const paragraphs = doc.body.querySelectorAll("p");
  const set = new Set(
    indices.filter(
      (n): n is number => typeof n === "number" && Number.isInteger(n) && n >= 0,
    ),
  );
  paragraphs.forEach((p, i) => {
    if (set.has(i)) p.classList.add("ai");
  });
  return doc.body.innerHTML;
}

export function useEditorSync(opts: UseEditorSyncOpts) {
  const {
    editor, activeChapter, dirty, setDirty, onSelectionChange,
    onToggleFocusMode, onToggleFind, onContinueWriting,
  } = opts;

  // Sync editor content from active chapter.
  useEffect(() => {
    if (!editor) return;
    // Plain text → HTML (paragraphs survive), then re-apply the persisted
    // AI-paragraph markers from the chapter's metadata (ai_paragraphs).
    const html = textToTipTapHTML(activeChapter?.content_text ?? "");
    const indices = (
      activeChapter?.metadata_json as Record<string, unknown> | undefined
    )?.ai_paragraphs;
    const marked = markAiParagraphs(html, indices);
    editor.chain().setContent(marked, false).setMeta("addToHistory", false).run();
    setDirty(false);
  }, [editor, activeChapter, setDirty]);

  // Track dirty state.
  useEffect(() => {
    if (!editor) return;
    const handler = () => setDirty(true);
    editor.on("update", handler);
    return () => { editor.off("update", handler); };
  }, [editor, setDirty]);

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
        onSelectionChange(editor.state.doc.textBetween(from, to, ""));
      } else {
        onSelectionChange("");
      }
    };
    editor.on("selectionUpdate", handler);
    return () => { editor.off("selectionUpdate", handler); };
  }, [editor, onSelectionChange]);

  // Focus mode / find / continue-writing shortcuts (R7-1 suite).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (matchesShortcut(e, "Ctrl+Shift+F")) {
        e.preventDefault();
        onToggleFocusMode();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "h") {
        e.preventDefault();
        onToggleFind();
        return;
      }
      if (matchesShortcut(e, "Ctrl+\\")) {
        e.preventDefault();
        onToggleFocusMode();
        return;
      }
      if (matchesShortcut(e, "Ctrl+F")) {
        e.preventDefault();
        onToggleFind();
        return;
      }
      if (matchesShortcut(e, "Ctrl+Enter")) {
        e.preventDefault();
        // The AI tool panel is hidden in focus mode; exit it so the user can
        // reach the continue-writing entry (matches the bar's hint text).
        onContinueWriting();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onToggleFocusMode, onToggleFind, onContinueWriting]);
}
