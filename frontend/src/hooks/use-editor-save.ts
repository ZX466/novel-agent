"use client";

/**
 * Editor save orchestration: manual save (Ctrl+S / toolbar), idle auto-save,
 * save-state surfacing (saving → saved → idle with a 1.5s hold), server-side
 * snapshot creation (best-effort, never blocks the save), and PATCH-merge
 * semantics for document metadata (only changed keys are sent so a concurrent
 * outline write is never clobbered by a stale full metadata copy).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { Editor as TiptapEditor } from "@tiptap/react";

import { updateDocument } from "@/lib/documents";
import { updateChapter } from "@/lib/chapters";
import { createSnapshot } from "@/lib/snapshots";
import { aiParagraphsMetadata } from "@/lib/ai-paragraphs";
import type { EditorDoc, DocumentPartial } from "@/lib/types";
import type { SaveState } from "@/hooks/use-documents";
import type { WritingSettings } from "@/components/WriterSettingsBar";

export function countWords(text: string): number {
  if (!text) return 0;
  const cjk = (text.match(/[一-鿿㐀-䶿豈-﫿]/g) || []).length;
  const latin = text.replace(/[一-鿿㐀-䶿豈-﫿]/g, " ").trim();
  const words = latin ? latin.split(/\s+/).filter(Boolean).length : 0;
  return cjk + words;
}

interface UseEditorSaveOpts {
  docId: number;
  doc: EditorDoc | null;
  editor: TiptapEditor | null;
  activeChapterId: number | null;
  activeChapterTitle: string | null;
  title: string;
  settings: WritingSettings;
  dirty: boolean;
  onSaved: (updated: EditorDoc) => void;
  onClean: () => void;
  refreshChapters: () => void;
}

export function useEditorSave(opts: UseEditorSaveOpts) {
  const {
    docId, doc, editor, activeChapterId, activeChapterTitle,
    title, settings, dirty, onSaved, onClean, refreshChapters,
  } = opts;

  const [saveState, setSaveState] = useState<SaveState>("idle");
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const performSave = useCallback(async () => {
    if (!editor || !doc) return;
    setSaveState("saving");
    try {
      const text = editor.getText();
      // Save current chapter content. metadata_json carries the AI-paragraph
      // markers (ai_paragraphs indices) so the .prose p.ai styling survives
      // reloads; the backend PATCHes the whole metadata dict (full replace
      // is fine here — chapter metadata only holds our marker + warnings).
      if (activeChapterId != null) {
        await updateChapter(docId, activeChapterId, {
          content_text: text,
          metadata_json: aiParagraphsMetadata(editor.getJSON()) as Record<string, unknown>,
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
      onSaved(updated);
      onClean();
      setSaveState("saved");
      // Create a server-side snapshot for history (best-effort).
      if (activeChapterId != null) {
        try {
          await createSnapshot(docId, activeChapterId, editor.getText(), {
            title: activeChapterTitle ?? "",
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
  }, [
    editor, doc, activeChapterId, activeChapterTitle, title, settings, docId,
    refreshChapters, onSaved, onClean,
  ]);

  const handleAutoSave = useCallback(() => {
    if (dirty) void performSave();
  }, [dirty, performSave]);

  const handleSave = useCallback(() => {
    if (dirty) void performSave();
  }, [dirty, performSave]);

  // Ctrl+S — manual save.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey) {
        if (e.key === "s" || e.key === "S") {
          e.preventDefault();
          if (dirty) void performSave();
        }
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

  return { saveState, performSave, handleSave, handleAutoSave };
}
