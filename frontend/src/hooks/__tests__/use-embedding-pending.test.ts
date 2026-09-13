import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useEmbeddingPending } from "../use-embedding-pending";

/**
 * Drives the "索引中" indicator: starts from the chapter's metadata flag,
 * flips true on each save response, and polls the chapter list until the
 * backend clears the flag (or gives up after max attempts — the badge then
 * hides without alarming, matching RAG's silent-degradation contract).
 */

type ChapterMeta = { metadata_json?: Record<string, unknown> };

function makeListChapters(results: Array<boolean>) {
  let call = 0;
  return vi.fn(async () => {
    const pending = results[Math.min(call, results.length - 1)];
    call++;
    return {
      items: [{ id: 1, metadata_json: { embedding_pending: pending } }],
    } as unknown as { items: ChapterMeta[] };
  });
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useEmbeddingPending", () => {
  it("starts pending when the chapter metadata carries the flag", () => {
    const { result } = renderHook(() =>
      useEmbeddingPending(1, { embedding_pending: true }, async () => ({ items: [] }), 10),
    );
    expect(result.current.pending).toBe(true);
  });

  it("not pending when metadata lacks the flag", () => {
    const { result } = renderHook(() =>
      useEmbeddingPending(1, {}, async () => ({ items: [] }), 10),
    );
    expect(result.current.pending).toBe(false);
  });

  it("polls after a save response sets pending, stops when cleared", async () => {
    const listChapters = makeListChapters([true, true, false]);
    const { result } = renderHook(() =>
      useEmbeddingPending(1, {}, listChapters as never, 10),
    );
    expect(result.current.pending).toBe(false);

    // Save response: backend returned metadata with the flag set.
    act(() => result.current.markPendingFromSave({ embedding_pending: true }));
    expect(result.current.pending).toBe(true);

    // First poll tick: still pending.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    expect(result.current.pending).toBe(true);
    // Second tick: still pending (first list result true).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    expect(result.current.pending).toBe(true);
    // Third tick: cleared → pending false, justIndexed true.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    expect(result.current.pending).toBe(false);
    expect(result.current.justIndexed).toBe(true);
    expect(listChapters).toHaveBeenCalledTimes(3);
  });

  it("stops polling after max attempts even if never cleared", async () => {
    const listChapters = makeListChapters([true]);
    const { result } = renderHook(() =>
      useEmbeddingPending(1, {}, listChapters as never, 10),
    );
    act(() => result.current.markPendingFromSave({ embedding_pending: true }));
    // 10 attempts at 3 s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000);
    });
    expect(result.current.pending).toBe(false);
    expect(result.current.justIndexed).toBe(false);
    expect(listChapters.mock.calls.length).toBeLessThanOrEqual(10);
  });

  it("justIndexed resets when a new save marks pending again", async () => {
    const listChapters = makeListChapters([false]);
    const { result } = renderHook(() =>
      useEmbeddingPending(1, {}, listChapters as never, 10),
    );
    act(() => result.current.markPendingFromSave({ embedding_pending: true }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    expect(result.current.justIndexed).toBe(true);
    act(() => result.current.markPendingFromSave({ embedding_pending: true }));
    expect(result.current.justIndexed).toBe(false);
    expect(result.current.pending).toBe(true);
  });
});
