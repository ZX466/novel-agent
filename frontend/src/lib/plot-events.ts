/**
 * Plot-event API client — nested under a document (novel).
 */
import {
  ApiError,
  type PlotEventListItem,
  type PlotEventRead,
} from "@/lib/types";
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

export interface ListPlotEventsResponse {
  items: PlotEventListItem[];
  total: number;
}

export interface PlotEventInput {
  chapter_id?: number | null;
  chapter_index?: number | null;
  event_type?: string;
  summary: string;
  prev_event_id?: number | null;
  involved_character_ids?: number[];
}

/**
 * R10-⑧ client-side cycle precheck for the predecessor dropdown: choosing
 * `chosenPrevId` as the predecessor of `editedId` forms a cycle when walking
 * `chosenPrevId`'s prev_event_id chain (over the WITH-choice snapshot)
 * reaches `editedId`. Warning-only server-side (R6-2) — this is the UX-layer
 * guard that keeps the option disabled before it can ever be saved.
 */
export function formsCycle(
  editedId: number,
  chosenPrevId: number | null,
  events: ReadonlyArray<{ id: number; prev_event_id?: number | null }>,
): boolean {
  if (chosenPrevId == null) return false;
  if (chosenPrevId === editedId) return true;
  const byId = new Map(events.map((e) => [e.id, e.prev_event_id]));
  let cursor: number | null = chosenPrevId;
  const seen = new Set<number>();
  while (cursor != null && !seen.has(cursor)) {
    if (cursor === editedId) return true;
    seen.add(cursor);
    cursor = byId.get(cursor) ?? null;
  }
  return false;
}

export async function listPlotEvents(
  docId: number,
  opts?: { limit?: number },
): Promise<ListPlotEventsResponse> {
  const limit = opts?.limit ?? 100;
  return request<ListPlotEventsResponse>(
    `/v1/documents/${docId}/plot-events?limit=${limit}`,
  );
}

export async function getPlotEvent(
  docId: number,
  eventId: number,
): Promise<PlotEventRead> {
  return request<PlotEventRead>(`/v1/documents/${docId}/plot-events/${eventId}`);
}

export async function createPlotEvent(
  docId: number,
  body: PlotEventInput,
): Promise<PlotEventRead> {
  return request<PlotEventRead>(`/v1/documents/${docId}/plot-events`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updatePlotEvent(
  docId: number,
  eventId: number,
  body: PlotEventInput,
): Promise<PlotEventRead> {
  return request<PlotEventRead>(
    `/v1/documents/${docId}/plot-events/${eventId}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

export async function deletePlotEvent(docId: number, eventId: number): Promise<void> {
  return request<void>(`/v1/documents/${docId}/plot-events/${eventId}`, {
    method: "DELETE",
  });
}
