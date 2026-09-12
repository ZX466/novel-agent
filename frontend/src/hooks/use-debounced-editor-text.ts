"use client";

/**
 * Debounced editor text extraction.
 *
 * `editor.getText()` walks the whole document; calling it on every render
 * (and counting words with a CJK regex on top) made typing janky on
 * longer chapters. Instead, schedule the extraction on a debounce timer:
 * typing keeps re-arming the timer, and one extraction happens after the
 * user pauses. `text` is then stable across unrelated re-renders.
 */
import { useEffect, useRef, useState } from "react";
import type { Editor as TiptapEditor } from "@tiptap/react";

export function useDebouncedEditorText(
  editor: TiptapEditor | null,
  delayMs = 300,
): { text: string } {
  const [text, setText] = useState("");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!editor) {
      setText("");
      return;
    }
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setText(editor.getText());
    }, delayMs);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [editor, delayMs]);

  return { text };
}
