/**
 * Timeline API client — causal DAG of plot events (R6-2).
 * Endpoint (backend app/api/timeline.py):
 *   GET /v1/documents/{docId}/timeline
 */
import { ApiError } from "@/lib/types";
import { backendUrl } from "@/lib/config";
import { ownerAuthHeaders } from "@/lib/settings";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${backendUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...ownerAuthHeaders(),
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

export interface TimelineNode {
  event_id: number;
  event_type: string;
  summary: string;
  chapter_id: number | null;
  chapter_index: number | null;
  in_world_date: string | null;
}

export interface TimelineEdge {
  from_id: number;
  to_id: number;
}

export interface TimelineWarning {
  kind: "predecessor" | "reverse_order" | "cycle";
  event_id: number;
  detail: string;
}

export interface TimelineResponse {
  nodes: TimelineNode[];
  edges: TimelineEdge[];
  warnings: TimelineWarning[];
  topological_order: number[];
}

export async function fetchTimeline(
  docId: number,
): Promise<TimelineResponse> {
  return request<TimelineResponse>(`/v1/documents/${docId}/timeline`);
}
