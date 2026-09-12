"use client";

/**
 * Document + chapter loading: fetches the editor document (restoring writing
 * settings from metadata_json) and the chapter list. Returns state plus
 * `refreshChapters` for post-mutation re-fetches.
 */
import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { getDocument } from "@/lib/documents";
import { listChapters } from "@/lib/chapters";
import type { EditorDoc, ChapterListItem } from "@/lib/types";
import type { WritingSettings } from "@/components/WriterSettingsBar";
import { DEFAULT_SETTINGS } from "@/components/WriterSettingsBar";

interface UseEditorDataResult {
  doc: EditorDoc | null;
  setDoc: Dispatch<SetStateAction<EditorDoc | null>>;
  docLoading: boolean;
  docError: string | null;
  title: string;
  setTitle: (t: string) => void;
  settings: WritingSettings;
  setSettings: (s: WritingSettings) => void;
  chapters: ChapterListItem[];
  setChapters: Dispatch<SetStateAction<ChapterListItem[]>>;
  chaptersLoading: boolean;
  refreshChapters: () => Promise<void>;
}

export function useEditorData(docId: number): UseEditorDataResult {
  const [doc, setDoc] = useState<EditorDoc | null>(null);
  const [docLoading, setDocLoading] = useState(true);
  const [docError, setDocError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [settings, setSettings] = useState<WritingSettings>(DEFAULT_SETTINGS);
  const [chapters, setChapters] = useState<ChapterListItem[]>([]);
  const [chaptersLoading, setChaptersLoading] = useState(true);

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

  useEffect(() => {
    void refreshChapters();
  }, [refreshChapters]);

  return {
    doc, setDoc, docLoading, docError,
    title, setTitle, settings, setSettings,
    chapters, setChapters, chaptersLoading, refreshChapters,
  };
}
