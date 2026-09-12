/**
 * Consistency sentinel API client (R5-3) — numeric-deterministic comparison
 * of draft content against stored character settings.
 * Endpoints (backend app/api/consistency.py):
 *   POST /v1/documents/{docId}/consistency/check
 *   GET  /v1/documents/{docId}/consistency/checks
 */
import { ApiError } from "@/lib/types";
import { backendUrl } from "@/lib/config";
import { embeddingProviderHeaders, ownerAuthHeaders } from "@/lib/settings";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${backendUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...ownerAuthHeaders(),
      ...embeddingProviderHeaders(),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
    } catch {
      // non-JSON error body
    }
    const msg =
      typeof detail === "string" ? detail : `请求失败 (${res.status})`;
    throw new ApiError(msg, res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface ConsistencyCheckItem {
  id: number;
  novel_id: number;
  chapter_id: number | null;
  target_type: string;
  target_id: number;
  target_name: string;
  verdict: string;
  detail: string;
  evidence_type: string | null;
  evidence_id: number | null;
  evidence_snippet: string | null;
  created_at: string;
}

export interface ConsistencyCheckListResponse {
  items: ConsistencyCheckItem[];
  total: number;
}

export interface ConsistencyCheckRequest {
  chapter_id?: number | null;
  content_text?: string | null;
}

/** Scan a draft (stored chapter or raw text) for setting conflicts. */
export async function runConsistencyCheck(
  docId: number,
  req: ConsistencyCheckRequest,
): Promise<ConsistencyCheckListResponse> {
  return request<ConsistencyCheckListResponse>(
    `/v1/documents/${docId}/consistency/check`,
    { method: "POST", body: JSON.stringify(req) },
  );
}

/** History of persisted checks for this novel. */
export async function listConsistencyChecks(
  docId: number,
): Promise<ConsistencyCheckListResponse> {
  return request<ConsistencyCheckListResponse>(
    `/v1/documents/${docId}/consistency/checks`,
  );
}
