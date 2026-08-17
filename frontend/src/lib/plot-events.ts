/**
 * Plot-event API client — nested under a document (novel).
 */
import {
  ApiError,
  type PlotEventListItem,
  type PlotEventRead,
} from "@/lib/types";
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

export interface ListPlotEventsResponse {
  items: PlotEventListItem[];
  total: number;
}

export interface PlotEventInput {
  chapter_id?: number | null;
  chapter_index?: number | null;
  event_type?: string;
  summary: string;
  involved_character_ids?: number[];
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
