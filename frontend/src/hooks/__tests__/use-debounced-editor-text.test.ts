import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDebouncedEditorText } from "../use-debounced-editor-text";
import type { Editor as TiptapEditor } from "@tiptap/react";

/**
 * currentText used to call editor.getText() on EVERY render — a full-doc
 * scan plus a CJK regex word count on each keystroke-driven re-render
 * (R10-⑤ 卡顿). The hook debounces the extraction so typing stays off the
 * hot path.
 *
 * 09-14 rewrite: the hook is now useSyncExternalStore + editor event
 * subscription. The old useState+useEffect version was INLINED by the
 * Next 14.2 production build into an IIFE where its effect never fired —
 * currentText stayed "" forever (本章字数 0, AI 工具上下文空, 无选中提示
 * 不显示). Tests drive the editor's event emitter directly now.
 */
describe("useDebouncedEditorText", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function makeEditor(text: string) {
    const handlers: Record<string, Set<() => void>> = {};
    return {
      getText: () => text,
      on: (ev: string, cb: () => void) => {
        (handlers[ev] ??= new Set()).add(cb);
      },
      off: (ev: string, cb: () => void) => {
        handlers[ev]?.delete(cb);
      },
      emit: (ev: string) => {
        handlers[ev]?.forEach((cb) => cb());
      },
    } as unknown as TiptapEditor & { emit: (ev: string) => void };
  }

  it("returns '' initially, then extracts after the debounce delay", () => {
    const editor = makeEditor("正文内容");
    const { result } = renderHook(() => useDebouncedEditorText(editor, 300));
    expect(result.current.text).toBe("");
    act(() => vi.advanceTimersByTime(350));
    expect(result.current.text).toBe("正文内容");
  });

  it("re-extracts when the editor emits update (typing), debounced", () => {
    const editor = makeEditor("初稿");
    const { result } = renderHook(() => useDebouncedEditorText(editor, 300));
    act(() => vi.advanceTimersByTime(350));
    expect(result.current.text).toBe("初稿");

    // Simulate typing: mutate source, fire update twice quickly →
    // debounce collapses them into one extraction of the final text.
    (editor as unknown as { getText: () => string }).getText = () => "第二版";
    act(() => {
      (editor as unknown as { emit: (ev: string) => void }).emit("update");
      (editor as unknown as { emit: (ev: string) => void }).emit("update");
      vi.advanceTimersByTime(100);
      (editor as unknown as { emit: (ev: string) => void }).emit("update");
    });
    act(() => vi.advanceTimersByTime(350));
    expect(result.current.text).toBe("第二版");
  });

  it("does not re-extract when unrelated rerenders happen after settling", () => {
    const editor = makeEditor("稳定文本");
    const getText = vi.spyOn(editor, "getText");
    const { rerender } = renderHook(() => useDebouncedEditorText(editor, 300));
    act(() => vi.advanceTimersByTime(350));
    expect(getText).toHaveBeenCalledTimes(1);
    const calls = getText.mock.calls.length;
    rerender();
    rerender();
    expect(getText.mock.calls.length).toBe(calls);
  });

  it("resets and re-extracts when the editor instance changes", () => {
    const a = makeEditor("A 文本");
    const b = makeEditor("B 文本");
    const { result, rerender } = renderHook(
      ({ ed }: { ed: TiptapEditor | null }) => useDebouncedEditorText(ed, 300),
      { initialProps: { ed: a as TiptapEditor | null } },
    );
    act(() => vi.advanceTimersByTime(350));
    expect(result.current.text).toBe("A 文本");
    rerender({ ed: b });
    act(() => vi.advanceTimersByTime(350));
    expect(result.current.text).toBe("B 文本");
  });

  it("handles null editor (editor not yet created)", () => {
    const { result } = renderHook(() => useDebouncedEditorText(null, 300));
    act(() => vi.advanceTimersByTime(500));
    expect(result.current.text).toBe("");
  });

  it("unsubscribes cleanly on unmount (no extraction after)", () => {
    const editor = makeEditor("卸载后安静");
    const getText = vi.spyOn(editor, "getText");
    const { unmount } = renderHook(() => useDebouncedEditorText(editor, 300));
    unmount();
    const calls = getText.mock.calls.length;
    act(() => vi.advanceTimersByTime(1000));
    expect(getText.mock.calls.length).toBe(calls);
  });
});
