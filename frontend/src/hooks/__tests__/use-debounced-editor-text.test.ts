import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDebouncedEditorText } from "../use-debounced-editor-text";
import type { Editor as TiptapEditor } from "@tiptap/react";

/**
 * currentText used to call editor.getText() on EVERY render — a full-doc
 * scan plus a CJK regex word count on each keystroke-driven re-render
 * (R10-⑤ 卡顿). The hook debounces the extraction so typing stays off the
 * hot path.
 */
describe("useDebouncedEditorText", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function makeEditor(text: string) {
    return { getText: () => text } as unknown as TiptapEditor;
  }

  it("returns '' initially without calling getText", () => {
    const editor = makeEditor("正文");
    const { result } = renderHook(() => useDebouncedEditorText(editor, 300));
    expect(result.current.text).toBe("");
  });

  it("extracts text after the debounce delay, not on every render", async () => {
    const editor = makeEditor("正文内容");
    const getText = vi.spyOn(editor, "getText");
    const { result, rerender } = renderHook(() => useDebouncedEditorText(editor, 300));
    rerender();
    rerender();
    // Before the delay: no extraction.
    expect(getText).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(350));
    expect(result.current.text).toBe("正文内容");
    expect(getText).toHaveBeenCalledTimes(1);
  });

  it("does not re-extract when unrelated rerenders happen after settling", () => {
    const editor = makeEditor("稳定文本");
    const getText = vi.spyOn(editor, "getText");
    const { result, rerender } = renderHook(() => useDebouncedEditorText(editor, 300));
    act(() => vi.advanceTimersByTime(350));
    expect(result.current.text).toBe("稳定文本");
    const calls = getText.mock.calls.length;
    rerender();
    rerender();
    expect(getText.mock.calls.length).toBe(calls);
  });

  it("resets the timer when the editor instance changes", () => {
    const a = makeEditor("A 文本");
    const b = makeEditor("B 文本");
    const { result, rerender } = renderHook(
      ({ ed }: { ed: TiptapEditor | null }) => useDebouncedEditorText(ed, 300),
      { initialProps: { ed: a as TiptapEditor | null } },
    );
    act(() => vi.advanceTimersByTime(200));
    rerender({ ed: b });
    act(() => vi.advanceTimersByTime(350));
    expect(result.current.text).toBe("B 文本");
  });

  it("handles null editor (editor not yet created)", () => {
    const { result } = renderHook(() => useDebouncedEditorText(null, 300));
    act(() => vi.advanceTimersByTime(500));
    expect(result.current.text).toBe("");
  });
});
