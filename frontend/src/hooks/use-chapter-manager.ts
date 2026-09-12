"use client";

/**
 * Chapter CRUD handlers for the editor: add (next-index aware — the outline
 * auto-create can occupy early indices, so length over-counts), select
 * (saving the current chapter first), delete, rename, and reorder.
 */
import { useCallback, useState, type Dispatch, type SetStateAction } from "react";
import type { Editor as TiptapEditor } from "@tiptap/react";

import {
  createChapter, deleteChapter, listChapters, reorderChapters, updateChapter,
} from "@/lib/chapters";
import type { ChapterListItem, ChapterRead } from "@/lib/types";

interface UseChapterManagerOpts {
  docId: number;
  editor: TiptapEditor | null;
  chapters: ChapterListItem[];
  setChapters: Dispatch<SetStateAction<ChapterListItem[]>>;
  activeChapter: ChapterRead | null;
  setActiveChapter: Dispatch<SetStateAction<ChapterRead | null>>;
  dirty: boolean;
  performSave: () => Promise<void>;
}

export function useChapterManager(opts: UseChapterManagerOpts) {
  const {
    docId, editor, chapters, setChapters, activeChapter, setActiveChapter,
    dirty, performSave,
  } = opts;
  const [activeChapterLoading, setActiveChapterLoading] = useState(false);

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
      setActiveChapter(() => ({
        ...ch,
        novel_id: docId,
        content_text: "",
        summary: "",
        metadata_json: {},
        created_at: ch.updated_at,
      }));
      if (editor) editor.commands.clearContent();
    } catch (e) {
      alert(e instanceof Error ? e.message : "创建章节失败");
    }
  }, [docId, chapters, editor, setChapters, setActiveChapter]);

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
        setActiveChapter(() => ({
          ...found,
          novel_id: docId,
          content_text: found.content_text ?? "",
          summary: "",
          // Keep server metadata (ai_paragraphs markers + timeline_warnings).
          metadata_json: found.metadata_json ?? {},
          created_at: found.updated_at,
        }));
      }
    } catch {
      // ignore
    } finally {
      setActiveChapterLoading(false);
    }
  }, [docId, dirty, performSave, setActiveChapter]);

  const handleDeleteChapter = useCallback(async (chapterId: number) => {
    if (!window.confirm("删除此章节？")) return;
    try {
      await deleteChapter(docId, chapterId);
      setChapters((prev) => prev.filter((c) => c.id !== chapterId));
      if (activeChapter?.id === chapterId) {
        setActiveChapter(() => null);
        if (editor) editor.commands.clearContent();
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "删除章节失败");
    }
  }, [docId, activeChapter, editor, setChapters, setActiveChapter]);

  const handleRenameChapter = useCallback(async (chapterId: number, newTitle: string) => {
    try {
      const updated = await updateChapter(docId, chapterId, { title: newTitle });
      setChapters((prev) =>
        prev.map((c) => (c.id === chapterId ? { ...c, title: updated.title } : c))
      );
      if (activeChapter?.id === chapterId) {
        setActiveChapter((p) => (p ? { ...p, title: updated.title } : null));
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "重命名失败");
    }
  }, [docId, activeChapter, setChapters, setActiveChapter]);

  const handleReorder = useCallback(async (orderedIds: Array<{ id: number; chapter_index: number }>) => {
    try {
      const r = await reorderChapters(docId, orderedIds);
      setChapters(() => r.items);
    } catch (e) {
      alert(e instanceof Error ? e.message : "排序失败");
    }
  }, [docId, setChapters]);

  return {
    activeChapterLoading,
    handleAddChapter,
    handleSelectChapter,
    handleDeleteChapter,
    handleRenameChapter,
    handleReorder,
  };
}
