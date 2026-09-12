/**
 * Shared outline→entity extraction pipeline used by both the editor's
 * "AI 提取" button and the apply-outline flow. Wraps extractEntitiesFromOutline
 * + batched best-effort creation (allSettled so one failed row never aborts
 * the rest) + a human-readable Chinese summary of created/skipped counts.
 */
import { extractEntitiesFromOutline } from "@/lib/extract-entities";
import { createCharacter } from "@/lib/characters";
import { createWorldSetting } from "@/lib/world-settings";
import { createPlotEvent } from "@/lib/plot-events";
import { ApiError } from "@/lib/types";

export interface ExtractionOutcome {
  characters: number;
  worldSettings: number;
  plotEvents: number;
  /** Rows rejected by server-side validation (e.g. duplicate name → 409). */
  failed: number;
  /** 409 conflicts specifically — duplicates already exist, skipped. */
  duplicates: number;
}

/** Run the extraction pipeline against `outlineText` for `docId`. */
export async function extractAndCreateEntities(
  docId: number,
  outlineText: string,
): Promise<ExtractionOutcome> {
  const entities = await extractEntitiesFromOutline(outlineText);

  const [charResults, wsResults, peResults] = await Promise.all([
    Promise.allSettled(
      entities.characters.map((ch) =>
        createCharacter(docId, {
          name: ch.name,
          role: ch.role || "其他",
          description: ch.description || "",
          arc_summary: ch.arc_summary || "",
        }),
      ),
    ),
    Promise.allSettled(
      entities.world_settings.map((ws) =>
        createWorldSetting(docId, {
          category: ws.category || "其他",
          title: ws.title,
          content_text: ws.content_text || "",
        }),
      ),
    ),
    Promise.allSettled(
      entities.plot_events.map((pe) =>
        createPlotEvent(docId, {
          summary: pe.summary,
          event_type: pe.event_type || "其他",
          chapter_index: pe.chapter_index ?? null,
        }),
      ),
    ),
  ]);

  const all = [...charResults, ...wsResults, ...peResults];
  const ok = all.filter((r) => r.status === "fulfilled").length;
  const rejected = all.filter(
    (r): r is PromiseRejectedResult =>
      r.status === "rejected" && r.reason instanceof ApiError,
  );
  const duplicates = rejected.filter((r) => (r.reason as ApiError).status === 409).length;
  const failed = all.length - ok;

  return {
    characters: charResults.filter((r) => r.status === "fulfilled").length,
    worldSettings: wsResults.filter((r) => r.status === "fulfilled").length,
    plotEvents: peResults.filter((r) => r.status === "fulfilled").length,
    failed,
    duplicates,
  };
}

/** Chinese summary line for alerts/status banners. Duplicates (409) get a
 *  friendly "已存在，已跳过" note instead of a bare failure count. */
export function formatExtractionSummary(o: ExtractionOutcome): string {
  const base = `已提取 ${o.characters} 个角色、${o.worldSettings} 个世界观设定、${o.plotEvents} 个剧情事件`;
  const nonDuplicate = o.failed - o.duplicates;
  if (o.duplicates > 0 && nonDuplicate <= 0) {
    return `${base}（${o.duplicates} 条已存在，已跳过）`;
  }
  if (o.failed > 0) {
    return `${base}（${o.duplicates} 条已存在跳过，${nonDuplicate} 条校验失败）`;
  }
  return base;
}
