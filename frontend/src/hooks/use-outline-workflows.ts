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
import type { EditorDoc } from "@/lib/types";
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

/** Parse outline heading lines → batched chapter creation with per-chapter
 *  summaries (text between this heading and the next, capped at 500 chars). */
async function createChaptersFromOutline(docId: number, outlineText: string) {
  const lines = outlineText.split("\n");
  const entries: Array<{ idx: number; title: string }> = [];
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (/^第[一二三四五六七八九十百千\d]+章/.test(trimmed)) {
      const title =
        trimmed.replace(/^\d+[\.\、]\s*/, "").trim().slice(0, 50) ||
        `第${entries.length + 1}章`;
      entries.push({ idx: i, title });
    }
  }
  for (let i = 0; i < entries.length; i++) {
    const start = entries[i].idx + 1;
    const end = i + 1 < entries.length ? entries[i + 1].idx : lines.length;
    const summaryLines = lines.slice(start, end).filter((l) => l.trim());
    const summary = summaryLines.join("\n").trim().slice(0, 500);
    await createChapter(docId, {
      chapter_index: i,
      title: entries[i].title,
      ...(summary ? { summary } : {}),
    });
  }
}

interface UseOutlineWorkflowsOpts {
  doc: EditorDoc | null;
  setDoc: Dispatch<SetStateAction<EditorDoc | null>>;
  docId: number;
  hasChapters: boolean;
  refreshChapters: () => Promise<void>;
  onPanelsMutated: () => void;
  onExtractedCharacters: () => void;
}

export function useOutlineWorkflows(opts: UseOutlineWorkflowsOpts) {
  const { doc, setDoc, docId, hasChapters, refreshChapters, onPanelsMutated, onExtractedCharacters } = opts;
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

        // Auto-create chapters from outline if none exist.
        // Also extract per-chapter summaries from the text between chapter headings.
        if (!hasChapters) {
          await createChaptersFromOutline(docId, outlineText);
          void refreshChapters();
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
    [doc, docId, hasChapters, refreshChapters, onPanelsMutated, onExtractedCharacters, setDoc],
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
