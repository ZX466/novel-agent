"use client";

/**
 * Drives the "索引中" / "✓ 已索引" embedding indicator (R10-⑤).
 *
 * The backend sets `metadata_json.embedding_pending = true` in the same
 * transaction as a content change and clears it once the background embed
 * has persisted the vector — between those points RAG retrieval does not
 * yet include the newest text. This hook:
 *   - starts from the chapter's loaded metadata,
 *   - flips pending on each save response that reports the flag,
 *   - polls the chapter list every 3 s (max 10 attempts) until cleared,
 *   - surfaces `justIndexed` for a short confirmation flash after clearing.
 *
 * If the flag never clears (embedding failure = RAG silently disabled for
 * the row, matching the backend's best-effort contract), polling gives up
 * and the badge hides without an alarm.
 */
import { useCallback, useEffect, useRef, useState } from "react";

const POLL_INTERVAL_MS = 3_000;
const MAX_POLLS = 10;

interface ChapterMetaLike {
  metadata_json?: Record<string, unknown> | null;
}

interface ListResult {
  items: ChapterMetaLike[];
}

export function useEmbeddingPending(
  chapterId: number | null,
  chapterMetadata: Record<string, unknown> | undefined | null,
  listChapters: (docId: number, limit?: number) => Promise<ListResult>,
  docId: number,
) {
  const [pending, setPending] = useState(false);
  const [justIndexed, setJustIndexed] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const attemptsRef = useRef(0);
  // Seed pending from chapter metadata ONCE per chapter — metadata object
  // identities change on unrelated re-renders, and a stale "no flag" value
  // must never clobber a just-marked pending state.
  const seededChapterRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Initial state from loaded chapter metadata.
  useEffect(() => {
    if (chapterId == null) {
      seededChapterRef.current = null;
      setPending(false);
      setJustIndexed(false);
      return;
    }
    if (seededChapterRef.current === chapterId) return; // already seeded
    seededChapterRef.current = chapterId;
    const flag = (chapterMetadata as Record<string, unknown> | null | undefined)
      ?.embedding_pending;
    setPending(flag === true);
  }, [chapterId, chapterMetadata]);

  // Poll loop while pending.
  useEffect(() => {
    if (!pending) {
      stopPolling();
      return;
    }
    attemptsRef.current = 0;
    pollRef.current = setInterval(async () => {
      attemptsRef.current += 1;
      if (attemptsRef.current >= MAX_POLLS) {
        // Embedding failed (or is extremely slow) — hide the badge quietly.
        setPending(false);
        return;
      }
      try {
        const r = await listChapters(docId, 500);
        const me = r.items.find((c) => (c as { id?: number }).id === chapterId);
        const flag = me?.metadata_json?.embedding_pending;
        if (flag !== true) {
          setPending(false);
          setJustIndexed(true);
        }
      } catch {
        // Transient poll errors don't affect the badge; next tick retries.
      }
    }, POLL_INTERVAL_MS);
    return stopPolling;
  }, [pending, chapterId, docId, listChapters, stopPolling]);

  // Save response hook-up: the PATCH response's metadata carries the flag.
  const markPendingFromSave = useCallback(
    (metadata: Record<string, unknown> | null | undefined) => {
      const flag = metadata?.embedding_pending;
      if (flag === true) {
        setJustIndexed(false);
        setPending(true);
      } else if (flag === false) {
        setPending(false);
        setJustIndexed(true);
      }
    },
    [],
  );

  return { pending, justIndexed, markPendingFromSave };
}
