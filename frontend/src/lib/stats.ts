/**
 * Stats dashboard API client — aggregates writing activity from the backend.
 *
 * Contract with backend `GET /v1/stats/dashboard` (Round 4, kilo domain):
 * {
 *   total_documents: number;
 *   total_chapters: number;
 *   total_words: number;
 *   streak_days: number;               // consecutive days with word count > 0
 *   today_words: number;
 *   daily_words: Array<{ date: string; words: number }>;  // last 30 days, ISO date
 * }
 */
import { ApiError } from "@/lib/types";
import { backendUrl } from "@/lib/config";
import { ownerAuthHeaders } from "@/lib/settings";

export interface DailyWords {
  date: string;
  words: number;
}

export interface StatsDashboard {
  total_documents: number;
  total_chapters: number;
  total_words: number;
  streak_days: number;
  today_words: number;
  daily_words: DailyWords[];
}

export async function fetchStatsDashboard(): Promise<StatsDashboard> {
  const res = await fetch(`${backendUrl}/v1/stats/dashboard`, {
    headers: { ...ownerAuthHeaders() },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
    } catch {
      // non-JSON body
    }
    const msg =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => String((d as { msg?: unknown }).msg ?? "")).filter(Boolean).join("；") || `HTTP ${res.status}`
          : `HTTP ${res.status}`;
    throw new ApiError(msg, res.status, detail);
  }
  return (await res.json()) as StatsDashboard;
}

/** Daily writing goal (local-only preference). */
const GOAL_KEY = "project11:writing-goal";

export function loadDailyGoal(): number {
  if (typeof window === "undefined") return 2000;
  const v = Number(window.localStorage.getItem(GOAL_KEY));
  return Number.isFinite(v) && v > 0 ? v : 2000;
}

export function saveDailyGoal(words: number): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(GOAL_KEY, String(Math.max(0, Math.floor(words))));
}
