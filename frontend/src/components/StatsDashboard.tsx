"use client";

import { useEffect, useMemo, useState } from "react";

import { ApiError } from "@/lib/types";
import {
  fetchStatsDashboard,
  loadDailyGoal,
  saveDailyGoal,
  type StatsDashboard,
} from "@/lib/stats";

function fmt(n: number): string {
  return n.toLocaleString("zh-CN");
}

function shortDate(iso: string): string {
  // "2026-08-17" -> "8/17"
  const [, m, d] = iso.split("-");
  return `${Number(m)}/${Number(d)}`;
}

/**
 * Writing stats dashboard — word count curve (30d), streak, daily goal.
 * Data comes from `GET /v1/stats/dashboard` (Round 4, kilo domain).
 */
export function StatsDashboard() {
  const [data, setData] = useState<StatsDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [goal, setGoal] = useState<number>(2000);
  const [goalDraft, setGoalDraft] = useState<string>("");

  useEffect(() => {
    setGoal(loadDailyGoal());
    setGoalDraft(String(loadDailyGoal()));
    fetchStatsDashboard()
      .then(setData)
      .catch((e) => {
        setError(e instanceof ApiError ? `${e.message}（统计接口或未就绪，接口由 kilo 提供）` : "加载失败");
      })
      .finally(() => setLoading(false));
  }, []);

  const chart = useMemo(() => {
    if (!data) return null;
    const days = data.daily_words.length > 0 ? data.daily_words : [];
    const max = Math.max(1, ...days.map((d) => d.words));
    const W = 640;
    const H = 160;
    const bw = days.length > 0 ? Math.max(3, W / days.length - 3) : 8;
    const bars = days.map((d, i) => {
      const h = Math.max(2, (d.words / max) * (H - 12));
      return (
        <rect
          key={d.date}
          x={i * (W / Math.max(1, days.length)) + 1}
          y={H - 10 - h}
          width={bw}
          height={h}
          rx={1.5}
          fill="var(--accent-muted)"
          opacity={0.85}
        >
          <title>{`${d.date}: ${fmt(d.words)} 字`}</title>
        </rect>
      );
    });
    // X labels: first, middle, last
    const labelIdx = [0, Math.floor((days.length - 1) / 2), days.length - 1];
    const labels = labelIdx
      .filter((i) => i >= 0 && i < days.length)
      .map((i) => (
        <text
          key={i}
          x={i * (W / Math.max(1, days.length)) + 1}
          y={H - 2}
          fontSize={8}
          fill="var(--fg-tertiary)"
        >
          {shortDate(days[i].date)}
        </text>
      ));
    return { bars, labels, W, H, max };
  }, [data]);

  const goalPct = data ? Math.min(100, Math.round((data.today_words / Math.max(1, goal)) * 100)) : 0;

  return (
    <div className="flex flex-col gap-sp-5 max-w-[720px] mx-auto w-full" style={{ color: "var(--fg)" }}>
      {error && (
        <div
          className="text-xs p-sp-4 rounded-md leading-relaxed"
          style={{ color: "var(--warn)", background: "oklch(0.74 0.10 85 / 0.06)", border: "1px solid oklch(0.74 0.10 85 / 0.12)" }}
        >
          ⚠️ {error}
        </div>
      )}
      {loading && !data && !error && (
        <div className="text-xs flex items-center gap-sp-2" style={{ color: "var(--muted)" }}>
          <span className="w-[5px] h-[5px] rounded-full" style={{ background: "var(--accent)", animation: "pulse 1.2s infinite" }} />
          加载统计数据…
        </div>
      )}

      {data && (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-sp-3">
            {[
              { label: "总字数", value: fmt(data.total_words) },
              { label: "章节数", value: fmt(data.total_chapters) },
              { label: "连续写作天数", value: fmt(data.streak_days) },
              { label: "今日字数", value: fmt(data.today_words) },
            ].map((s) => (
              <div
                key={s.label}
                className="p-sp-4 rounded-md border"
                style={{ background: "var(--surface)", borderColor: "var(--border-hairline)" }}
              >
                <div className="text-[10px] uppercase tracking-wide" style={{ color: "var(--muted)" }}>
                  {s.label}
                </div>
                <div className="mt-1 font-mono text-[20px] font-semibold tabular-nums" style={{ color: "var(--fg)" }}>
                  {s.value}
                </div>
              </div>
            ))}
          </div>

          {/* 30-day curve */}
          <div className="p-sp-4 rounded-md border" style={{ background: "var(--surface)", borderColor: "var(--border-hairline)" }}>
            <div className="flex items-center justify-between mb-sp-3">
              <span className="text-[11px] font-semibold" style={{ color: "var(--fg-secondary)" }}>
                近 30 天字数曲线
              </span>
              <span className="text-[10px]" style={{ color: "var(--muted)" }}>
                峰值 {fmt(chart?.max ?? 0)} 字
              </span>
            </div>
            {chart && (
              <svg viewBox={`0 0 ${chart.W} ${chart.H}`} className="w-full h-auto" role="img" aria-label="近 30 天每日字数柱状图">
                {chart.bars}
                {chart.labels}
              </svg>
            )}
          </div>

          {/* Daily goal */}
          <div className="p-sp-4 rounded-md border" style={{ background: "var(--surface)", borderColor: "var(--border-hairline)" }}>
            <div className="flex items-center justify-between mb-sp-2">
              <span className="text-[11px] font-semibold" style={{ color: "var(--fg-secondary)" }}>
                今日目标
              </span>
              <div className="flex items-center gap-sp-2">
                <input
                  type="number"
                  min={0}
                  step={500}
                  value={goalDraft}
                  onChange={(e) => setGoalDraft(e.target.value)}
                  onBlur={() => {
                    const v = Number(goalDraft);
                    if (Number.isFinite(v) && v >= 0) {
                      setGoal(v);
                      saveDailyGoal(v);
                    } else {
                      setGoalDraft(String(goal));
                    }
                  }}
                  className="w-[96px] px-sp-2 py-sp-1 rounded-sm text-[11px] font-mono outline-none border"
                  style={{ background: "var(--bg)", borderColor: "var(--border)", color: "var(--fg)" }}
                />
                <span className="text-[10px]" style={{ color: "var(--muted)" }}>字/天</span>
              </div>
            </div>
            <div className="h-[10px] rounded-full overflow-hidden" style={{ background: "var(--surface-2)" }}>
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${goalPct}%`,
                  background: goalPct >= 100 ? "var(--success)" : "var(--accent)",
                }}
              />
            </div>
            <div className="mt-sp-1.5 text-[10px] tabular-nums" style={{ color: "var(--muted)" }}>
              {fmt(data.today_words)} / {fmt(goal)} 字（{goalPct}%）
              {goalPct >= 100 && " 🎉 今日目标已达成"}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
