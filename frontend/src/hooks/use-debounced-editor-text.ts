"use client";

/**
 * Debounced editor text extraction.
 *
 * `editor.getText()` walks the whole document; calling it on every render
 * (and counting words with a CJK regex on top) made typing janky on
 * longer chapters. Instead, schedule the extraction on a debounce timer:
 * typing keeps re-arming the timer, and one extraction happens after the
 * user pauses. `text` is then stable across unrelated re-renders.
 *
 * 09-14: implemented with useSyncExternalStore instead of the previous
 * useState+useEffect pair. Reason: Next 14.2's production build INLINED
 * this module into the page component as an IIFE, and hooks called inside
 * an IIFE silently break — the effect never fired, so `text` stayed ""
 * forever (症状: 本章字数恒 0、AI 工具 editorText 恒空、无选中提示不显示、
 * 一致性检查"没有可查内容")。useSyncExternalStore is a single call whose
 * semantics survive inlining: the store owns the timer, React only reads.
 */
import { useMemo, useSyncExternalStore } from "react";
import type { Editor as TiptapEditor } from "@tiptap/react";

interface DebouncedTextStore {
  subscribe: (onStoreChange: () => void) => () => void;
  getSnapshot: () => string;
}

function createDebouncedTextStore(
  editor: TiptapEditor | null,
  delayMs: number,
): DebouncedTextStore {
  let cached = "";
  let timer: ReturnType<typeof setTimeout> | null = null;
  const listeners = new Set<() => void>();

  const flush = () => {
    timer = null;
    const next = editor ? editor.getText() : "";
    if (next !== cached) {
      cached = next;
      for (const l of listeners) l();
    }
  };

  return {
    subscribe(onStoreChange) {
      listeners.add(onStoreChange);
      if (editor) {
        // Any editor mutation re-arms the debounce; one extraction on pause.
        const rearm = () => {
          if (timer) clearTimeout(timer);
          timer = setTimeout(flush, delayMs);
        };
        editor.on("update", rearm);
        editor.on("selectionUpdate", rearm);
        // Initial extraction (chapter load / first mount).
        if (timer) clearTimeout(timer);
        timer = setTimeout(flush, delayMs);
        return () => {
          listeners.delete(onStoreChange);
          editor.off("update", rearm);
          editor.off("selectionUpdate", rearm);
          if (timer) clearTimeout(timer);
          timer = null;
        };
      }
      // No editor: keep cached empty, still a valid no-op subscription.
      return () => {
        listeners.delete(onStoreChange);
      };
    },
    getSnapshot: () => cached,
  };
}

export function useDebouncedEditorText(
  editor: TiptapEditor | null,
  delayMs = 300,
): { text: string } {
  // The store must be stable per (editor, delayMs) — useMemo keeps the same
  // store instance across renders so subscriptions aren't torn down.
  const store = useMemo(
    () => createDebouncedTextStore(editor, delayMs),
    [editor, delayMs],
  );
  const text = useSyncExternalStore(store.subscribe, store.getSnapshot, () => "");
  return { text };
}
