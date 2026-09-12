"use client";

/**
 * Find & replace state machine over the Tiptap document: builds a match list
 * from text nodes, cycles through matches (next/prev wrap), replaces the
 * current match, or replaces all matches (end→start so positions survive).
 */
import { useCallback, useMemo, useRef, useState } from "react";
import type { Editor as TiptapEditor } from "@tiptap/react";

import { textToParagraphNodes } from "@/lib/insert-text";

interface Match {
  from: number;
  to: number;
}

function buildMatchList(editor: TiptapEditor, query: string): Match[] {
  if (!query) return [];
  const doc = editor.state.doc;
  const matches: Match[] = [];
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
}

export function useFindReplace(editor: TiptapEditor | null) {
  const [findMatches, setFindMatches] = useState<Match[]>([]);
  const [findIndex, setFindIndex] = useState(-1);
  const findQueryRef = useRef<string>("");

  const handleFind = useCallback(
    (query: string) => {
      findQueryRef.current = query;
      if (!editor || !query) {
        setFindMatches([]);
        setFindIndex(-1);
        return;
      }
      const matches = buildMatchList(editor, query);
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
    [editor],
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
        .insertContentAt(m.from, textToParagraphNodes(replacement))
        .run();
      // Rebuild matches after replace.
      const newMatches = buildMatchList(editor, query);
      setFindMatches(newMatches);
      // Keep index at same position (now points to next match or wraps).
      const newIdx = Math.min(findIndex, newMatches.length - 1);
      setFindIndex(newIdx);
      if (newMatches.length > 0 && newIdx >= 0) {
        const nm = newMatches[newIdx];
        editor.chain().focus().setTextSelection({ from: nm.from, to: nm.to }).run();
      }
    },
    [editor, findMatches, findIndex],
  );

  const handleReplaceAll = useCallback(
    (query: string, replacement: string) => {
      if (!editor || !query) return;
      // Replace from end to start to preserve positions.
      const matches = buildMatchList(editor, query);
      for (let i = matches.length - 1; i >= 0; i--) {
        const m = matches[i];
        editor
          .chain()
          .deleteRange({ from: m.from, to: m.to })
          .insertContentAt(m.from, textToParagraphNodes(replacement))
          .run();
      }
      setFindMatches([]);
      setFindIndex(-1);
    },
    [editor],
  );

  const matchDisplay = useMemo(() => {
    if (findMatches.length === 0) return null;
    return `${findIndex + 1} / ${findMatches.length}`;
  }, [findMatches, findIndex]);

  return {
    handleFind,
    handleFindNext,
    handleFindPrev,
    handleReplace,
    handleReplaceAll,
    matchDisplay,
  };
}
