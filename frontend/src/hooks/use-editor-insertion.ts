"use client";

/**
 * AI insertion into the editor with pre-insertion snapshots (insert/replace
 * reasons) so the author can always roll back an AI edit.
 */
import { useCallback } from "react";
import type { Editor as TiptapEditor } from "@tiptap/react";

import { createSnapshot } from "@/lib/snapshots";
import { aiTextToParagraphNodes } from "@/lib/insert-text";
import type { ChapterRead } from "@/lib/types";

interface UseEditorInsertionOpts {
  docId: number;
  editor: TiptapEditor | null;
  activeChapter: ChapterRead | null;
}

export function useEditorInsertion(opts: UseEditorInsertionOpts) {
  const { docId, editor, activeChapter } = opts;

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
      editor?.chain().focus().insertContent(aiTextToParagraphNodes(text)).run();
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
        editor.chain().focus().deleteRange({ from, to }).insertContentAt(from, aiTextToParagraphNodes(text)).run();
      } else {
        editor.chain().focus().insertContent(aiTextToParagraphNodes(text)).run();
      }
    },
    [editor, docId, activeChapter],
  );

  return { handleInsertIntoEditor, handleReplaceInEditor };
}
