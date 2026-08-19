/**
 * Chapter snapshot API client (R5-4 安心回溯).
 *
 * Snapshots are immutable point-in-time copies of a chapter's text, created
 * automatically before risky editing operations (AI insert / whole-chapter
 * replace / export) and on manual save. This client creates, lists,
 * restores, and deletes them; every call is owner- and document-scoped via
 * X-API-Key + doc_id.
 */
import {
  ApiError,
  type ChapterRead,
  type ChapterSnapshot,
  type SnapshotListResponse,
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
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "detail" in (detail as object)
          ? String((detail as { detail: unknown }).detail)
          : `请求失败 (${res.status})`;
    throw new ApiError(msg, res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface CreateSnapshotOptions {
  title?: string;
  reason?: string;
}

/** POST — persist a snapshot of the given text. Returns the stored snapshot. */
export async function createSnapshot(
  docId: number,
  chapterId: number,
  contentText: string,
  options: CreateSnapshotOptions = {},
): Promise<ChapterSnapshot> {
  return request<ChapterSnapshot>(
    `/v1/documents/${docId}/chapters/${chapterId}/snapshots`,
    {
      method: "POST",
      body: JSON.stringify({
        content_text: contentText,
        ...(options.title ? { title: options.title } : {}),
        ...(options.reason ? { reason: options.reason } : {}),
      }),
    },
  );
}

/** GET — newest-first page of snapshots for a chapter. */
export async function listSnapshots(
  docId: number,
  chapterId: number,
  limit = 50,
  offset = 0,
): Promise<SnapshotListResponse> {
  return request<SnapshotListResponse>(
    `/v1/documents/${docId}/chapters/${chapterId}/snapshots?limit=${limit}&offset=${offset}`,
  );
}

/** POST — copy a snapshot's text back onto the chapter. Returns updated chapter. */
export async function restoreSnapshot(
  docId: number,
  chapterId: number,
  snapshotId: number,
): Promise<ChapterRead> {
  return request<ChapterRead>(
    `/v1/documents/${docId}/chapters/${chapterId}/snapshots/${snapshotId}/restore`,
    { method: "POST" },
  );
}

/** DELETE — remove a snapshot from history. */
export async function deleteSnapshot(
  docId: number,
  chapterId: number,
  snapshotId: number,
): Promise<void> {
  return request<void>(
    `/v1/documents/${docId}/chapters/${chapterId}/snapshots/${snapshotId}`,
    { method: "DELETE" },
  );
}
