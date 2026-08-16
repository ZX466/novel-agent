/**
 * BYOK ProviderConfig persistence — localStorage helpers plus stage/preset
 * utilities. Mirrors the hooks/use-provider-config.ts React wrapper.
 */
import type {
  AllStageKey,
  ProviderConfig,
  StageConfig,
  StageKey,
} from "@/lib/types";
import { ALL_STAGE_KEYS, STAGE_KEYS } from "@/lib/types";

const STORAGE_KEY = "novel-agent.provider-config";

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

export function loadProviderConfig(): ProviderConfig | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ProviderConfig;
    return parsed;
  } catch {
    return null;
  }
}

export function saveProviderConfig(cfg: ProviderConfig): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
}

export function clearProviderConfig(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}

// ---------------------------------------------------------------------------
// Completeness checks
// ---------------------------------------------------------------------------

export function isStageComplete(stage: StageConfig | undefined | null): boolean {
  if (!stage) return false;
  return Boolean(stage.api_base && stage.api_key && stage.model);
}

/** True only when ALL THREE chat stages are fully configured. */
export function isProviderConfigComplete(cfg: ProviderConfig | null): boolean {
  if (!cfg) return false;
  return STAGE_KEYS.every((k) => isStageComplete(cfg[k]));
}

/** Return a config with every stage in the "empty" placeholder state. */
export function emptyProviderConfig(): ProviderConfig {
  return {
    draft: emptyStage(),
    refine: emptyStage(),
    evaluate: emptyStage(),
    embedding: emptyStage(),
  };
}

export function emptyStage(): StageConfig {
  return { api_base: "", api_key: "", model: "", extra_headers: {} };
}

/** Pick the non-empty stages out of a config (used before sending to backend). */
export function resolvedProviderConfig(
  cfg: ProviderConfig | null,
): ProviderConfig | null {
  if (!cfg) return null;
  const next: ProviderConfig = { draft: cfg.draft, refine: cfg.refine, evaluate: cfg.evaluate };
  for (const k of STAGE_KEYS) {
    if (!isStageComplete(cfg[k])) {
      // Keep as-is; backend falls back to .env per-stage when missing.
    }
  }
  if (cfg.embedding && isStageComplete(cfg.embedding)) {
    next.embedding = cfg.embedding;
  }
  return next;
}

/** Clear the in-memory embedding cache on the backend (used when model/dim changes). */
export async function clearEmbeddingCache(): Promise<void> {
  try {
    const base = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
    await fetch(`${base}/v1/embedding/cache`, { method: "DELETE" });
  } catch {
    // Best-effort — the endpoint may not exist; cache invalidation is a hint.
  }
}

export function isStageConfigured(cfg: ProviderConfig | null, key: AllStageKey): boolean {
  if (!cfg) return false;
  const stage = cfg[key as keyof ProviderConfig];
  return isStageComplete(stage as StageConfig | null | undefined);
}
