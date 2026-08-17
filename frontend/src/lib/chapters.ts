/**
 * Chapter API client — nested under a document (novel).
 */
import {
  ApiError,
  type ChapterInput,
  type ChapterListItem,
  type ChapterRead,
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
        : `请求失败 (${res.status})`;
    throw new ApiError(msg, res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface ListChaptersResponse {
  items: ChapterListItem[];
  total: number;
}

export async function listChapters(
  docId: number,
  limit = 200,
): Promise<ListChaptersResponse> {
  return request<ListChaptersResponse>(
    `/v1/documents/${docId}/chapters?limit=${limit}`,
  );
}

export async function createChapter(
  docId: number,
  body: ChapterInput,
): Promise<ChapterRead> {
  return request<ChapterRead>(`/v1/documents/${docId}/chapters`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateChapter(
  docId: number,
  chapterId: number,
  body: ChapterInput,
): Promise<ChapterRead> {
  return request<ChapterRead>(
    `/v1/documents/${docId}/chapters/${chapterId}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

export async function deleteChapter(docId: number, chapterId: number): Promise<void> {
  return request<void>(`/v1/documents/${docId}/chapters/${chapterId}`, {
    method: "DELETE",
  });
}

export async function reorderChapters(
  docId: number,
  ordered: Array<{ id: number; chapter_index: number }>,
): Promise<ListChaptersResponse> {
  return request<ListChaptersResponse>(
    `/v1/documents/${docId}/chapters/reorder`,
    {
      method: "PUT",
      body: JSON.stringify({ chapters: ordered }),
    },
  );
}
