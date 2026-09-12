"use client";
/**
 * StageProgress — R9-② pipeline visibility UI.
 *
 * Renders the three-stage pipeline skeleton (retrieval → draft → refine →
 * evaluate → safety) and lights stages up from backend `stage` events.
 * Tolerates missing events (M2): stages never started by the backend stay
 * "pending"; the component hides itself entirely when no event has arrived
 * so non-streaming fallback paths degrade to the existing isBusy display.
 */
import { useCallback, useMemo, useState } from "react";
import type { StageEvent } from "@/lib/perf-transport";

type StageStatus = "pending" | "started" | "succeeded" | "failed" | "skipped";

interface StageState {
  status: StageStatus;
  elapsedMs?: number;
  code?: string;
  iteration?: number;
}

const STAGES: Array<{ key: string; label: string }> = [
  { key: "retrieval", label: "检索记忆" },
  { key: "draft", label: "初稿" },
  { key: "refine", label: "精修" },
  { key: "evaluate", label: "评审" },
  { key: "safety_check", label: "安全检查" },
];

const STATUS_ICON: Record<StageStatus, string> = {
  pending: "○",
  started: "◐",
  succeeded: "●",
  failed: "✕",
  skipped: "◌",
};

const STATUS_COLOR: Record<StageStatus, string> = {
  pending: "var(--fg-tertiary)",
  started: "var(--accent)",
  succeeded: "var(--ok, #4a9)",
  failed: "var(--danger, #d55)",
  skipped: "var(--fg-tertiary)",
};

export function useStageProgress() {
  const [stages, setStages] = useState<Record<string, StageState>>({});
  const [visible, setVisible] = useState(false);

  const applyEvent = useCallback((event: StageEvent) => {
    setVisible(true);
    if (event.type === "pipeline_start") return; // skeleton becomes visible
    if (event.type === "stage" && event.stage) {
      setStages((prev) => ({
        ...prev,
        [event.stage as string]: {
          status: (event.status as StageStatus) ?? "started",
          elapsedMs: event.elapsed_ms,
          code: event.code,
          iteration: event.iteration,
        },
      }));
    }
  }, []);

  const reset = useCallback(() => {
    setStages({});
    setVisible(false);
  }, []);

  return { stages, visible, applyEvent, reset };
}

export function StageProgress({
  stages,
  visible,
}: {
  stages: Record<string, StageState>;
  visible: boolean;
}) {
  const hasAny = useMemo(
    () => STAGES.some((s) => stages[s.key] !== undefined),
    [stages],
  );
  // M2 tolerance: no backend events at all → render nothing.
  if (!visible || !hasAny) return null;

  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 px-sp-3 py-sp-2 rounded-sm text-[11px]"
      style={{ background: "var(--surface)", border: "1px solid var(--border-subtle)" }}
      aria-live="polite"
    >
      {STAGES.map((s, i) => {
        const st = stages[s.key] ?? { status: "pending" as StageStatus };
        const color = STATUS_COLOR[st.status];
        return (
          <span key={s.key} className="flex items-center gap-1" style={{ color }}>
            <span aria-hidden>{STATUS_ICON[st.status]}</span>
            <span
              style={{
                color: st.status === "pending" ? "var(--fg-tertiary)" : color,
                fontWeight: st.status === "started" ? 600 : 400,
              }}
            >
              {s.label}
            </span>
            {st.status === "succeeded" && st.elapsedMs != null && (
              <span style={{ color: "var(--fg-tertiary)" }}>{Math.round(st.elapsedMs)}ms</span>
            )}
            {st.status === "failed" && st.code && (
              <span style={{ color: "var(--fg-tertiary)" }}>({st.code})</span>
            )}
            {st.status === "skipped" && (
              <span style={{ color: "var(--fg-tertiary)" }}>跳过</span>
            )}
            {i < STAGES.length - 1 && (
              <span style={{ color: "var(--border-subtle)" }}>·</span>
            )}
          </span>
        );
      })}
    </div>
  );
}
