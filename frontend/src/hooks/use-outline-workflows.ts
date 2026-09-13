"use client";

/**
 * Outline workflows: apply-outline (save metadata + auto-create chapters +
 * auto-extract entities), save-outline (metadata only), and the standalone
 * "AI 提取" pass. All metadata writes PATCH-merge only the outline keys so a
 * concurrent settings write is never clobbered by a stale full copy.
 */
import { useCallback, useState, type Dispatch, type SetStateAction } from "react";

import { updateDocument } from "@/lib/documents";
import { createChapter } from "@/lib/chapters";
import type { ChapterListItem, EditorDoc } from "@/lib/types";
import {
  extractAndCreateEntities,
  formatExtractionSummary,
} from "@/lib/entity-extraction";

/** PATCH-merge only the outline keys into document metadata (row-locked on
 *  the server, so a concurrent settings write is never clobbered). */
async function updateOutlineMetadata(docId: number, outlineText: string) {
  await updateDocument(docId, {
    metadata_json: {
      outline: outlineText,
      outline_updated_at: new Date().toISOString(),
    },
    merge_metadata: true,
  });
}

/** Parse outline heading lines → chapter titles (R10-⑨: title-only parsing
 *  is volume-outline friendly — 1000+ chapter outlines carry just
 *  「第X章 题目」 lines under 卷 blocks, no per-chapter synopsis needed). */
function parseOutlineChapters(outlineText: string): Array<{ idx: number; title: string; summary: string }> {
  const lines = outlineText.split("\n");
  const entries: Array<{ idx: number; title: string; summary: string }> = [];
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (/^第[一二三四五六七八九十百千零〇两\d]+章/.test(trimmed)) {
      const title =
        trimmed.replace(/^\d+[\.\、]\s*/, "").trim().slice(0, 200) ||
        `第${entries.length + 1}章`;
      entries.push({ idx: i, title, summary: "" });
    }
  }
  // Non-volume outlines still carry per-chapter synopsis lines between
  // headings — fill summaries only when there is intervening text.
  for (let i = 0; i < entries.length; i++) {
    const start = entries[i].idx + 1;
    const end = i + 1 < entries.length ? entries[i + 1].idx : lines.length;
    const summaryLines = lines.slice(start, end).filter((l) => l.trim() && !/^第[一二三四五六七八九十百千零〇两\d]+卷/.test(l.trim()));
    entries[i].summary = summaryLines.join("\n").trim().slice(0, 500);
  }
  return entries;
}

/** Create chapters parsed from the outline. R10-⑨: runs in small concurrent
 *  batches — a sequential await per chapter made 1000-chapter applies take
 *  minutes; batches of 10 keep server load sane while finishing ~100x faster
 *  than serial. Skips indexes that already exist so re-applying an updated
 *  outline tops up new chapters instead of erroring on duplicates. */
async function createChaptersFromOutline(
  docId: number,
  entries: Array<{ idx: number; title: string; summary: string }>,
  existingIndexes: Set<number>,
) {
  const BATCH = 10;
  for (let start = 0; start < entries.length; start += BATCH) {
    const batch = entries
      .slice(start, start + BATCH)
      .map((e, i) => ({ ...e, chapter_index: start + i }))
      .filter((e) => !existingIndexes.has(e.chapter_index));
    await Promise.all(
      batch.map((e) =>
        createChapter(docId, {
          chapter_index: e.chapter_index,
          title: e.title,
          ...(e.summary ? { summary: e.summary } : {}),
        }).catch(() => undefined), // duplicate-index races: skip, keep applying
      ),
    );
  }
}

interface UseOutlineWorkflowsOpts {
  doc: EditorDoc | null;
  setDoc: Dispatch<SetStateAction<EditorDoc | null>>;
  docId: number;
  hasChapters: boolean;
  /** Current chapter list — R10-⑨ uses chapter_index values to top up only
   *  missing chapters when re-applying a grown volume outline. */
  chapters: ChapterListItem[];
  refreshChapters: () => Promise<void>;
  onPanelsMutated: () => void;
  onExtractedCharacters: () => void;
}

export function useOutlineWorkflows(opts: UseOutlineWorkflowsOpts) {
  const { doc, setDoc, docId, refreshChapters, chapters, onPanelsMutated, onExtractedCharacters } = opts;
  const [extracting, setExtracting] = useState(false);

  const handleApplyOutline = useCallback(
    async (outlineText: string) => {
      if (!doc) return;
      try {
        // Save outline to document metadata. Send ONLY the changed keys —
        // the server PATCH-merges under a row lock, so a concurrent write to
        // a different metadata key (e.g. settings) is never clobbered by a
        // stale full-copy being replayed. Local state still merges in place.
        await updateOutlineMetadata(docId, outlineText);
        setDoc((prev) =>
          prev
            ? {
                ...prev,
                metadata_json: {
                  ...(prev.metadata_json ?? {}),
                  outline: outlineText,
                  outline_updated_at: new Date().toISOString(),
                },
              }
            : prev,
        );

        // R10-⑨: ALWAYS sync chapters from the outline (not just when the
        // novel has none) — a volume outline (1000+ 章) is re-applied as it
        // grows; new 「第X章」 lines top up the chapter list in place.
        // Existing indexes are skipped, so nothing is duplicated or reset.
        const entries = parseOutlineChapters(outlineText);
        if (entries.length > 0) {
          const existingIndexes = new Set(
            chapters.map((c) => c.chapter_index).filter((n): n is number => n != null),
          );
          const missing = entries.filter((_, i) => !existingIndexes.has(i));
          if (missing.length > 0) {
            await createChaptersFromOutline(docId, entries, existingIndexes);
            void refreshChapters();
          }
        }

        // Auto-extract characters/world/events from outline.
        try {
          setExtracting(true);
          const outcome = await extractAndCreateEntities(docId, outlineText);
          // Force panels to remount and re-fetch.
          onPanelsMutated();
          if (outcome.characters > 0) {
            onExtractedCharacters();
          }
          alert(`✅ 大纲已保存，${formatExtractionSummary(outcome)}`);
        } catch (extractErr) {
          const msg =
            extractErr instanceof Error ? extractErr.message : "提取失败";
          alert(
            `✅ 大纲已保存（自动提取失败：${msg}，可手动点 AI 提取）\n\n提示：请先在设置中测试 API 连接是否正常`,
          );
        } finally {
          setExtracting(false);
        }
      } catch (e) {
        alert(e instanceof Error ? e.message : "保存大纲失败");
      }
    },
    [doc, docId, chapters, refreshChapters, onPanelsMutated, onExtractedCharacters, setDoc],
  );

  const handleSaveOutline = useCallback(
    async (text: string) => {
      if (!doc) return;
      try {
        // Same send-only-changed-keys contract as handleApplyOutline above.
        await updateOutlineMetadata(docId, text);
        setDoc((prev) =>
          prev
            ? {
                ...prev,
                metadata_json: {
                  ...(prev.metadata_json ?? {}),
                  outline: text,
                  outline_updated_at: new Date().toISOString(),
                },
              }
            : prev,
        );
      } catch (e) {
        alert(e instanceof Error ? e.message : "保存大纲失败");
      }
    },
    [doc, docId, setDoc],
  );

  const handleExtractEntities = useCallback(async () => {
    const outlineText = (doc?.metadata_json as Record<string, unknown> | undefined)?.outline as string | undefined;
    if (!outlineText) {
      alert("请先生成或编写大纲");
      return;
    }
    setExtracting(true);
    try {
      const outcome = await extractAndCreateEntities(docId, outlineText);
      // Force all panels to remount so they re-fetch fresh data regardless of
      // which tab is currently active (avoids the no-op setLeftTab bug).
      onPanelsMutated();
      if (outcome.characters > 0) {
        onExtractedCharacters();
      }
      alert(`✅ ${formatExtractionSummary(outcome)}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "提取失败";
      alert(`❌ 提取失败：${msg}\n\n请检查：1) 自定义 API 配置是否正确（设置 → 测试连接）；2) 大纲内容是否完整`);
    } finally {
      setExtracting(false);
    }
  }, [doc, docId, onPanelsMutated, onExtractedCharacters]);

  return { extracting, handleApplyOutline, handleSaveOutline, handleExtractEntities };
}
