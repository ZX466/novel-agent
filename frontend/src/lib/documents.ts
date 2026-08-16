/**
 * Document API client — CRUD for works (作品) against the FastAPI backend.
 */
import {
  ApiError,
  type DocumentInput,
  type DocumentPartial,
  type EditorDoc,
  type EditorDocListItem,
  type DocumentListFilters,
} from "@/lib/types";
import { backendUrl } from "@/lib/config";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${backendUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
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

export interface ListDocumentsResponse {
  items: EditorDocListItem[];
  total: number;
}

export async function listDocuments(
  filters?: DocumentListFilters,
): Promise<ListDocumentsResponse> {
  const params = new URLSearchParams();
  if (filters) {
    if (filters.limit != null) params.set("limit", String(filters.limit));
    if (filters.offset != null) params.set("offset", String(filters.offset));
    if (filters.type) params.set("type", filters.type);
    if (filters.category) params.set("category", filters.category);
    if (filters.search) params.set("search", filters.search);
    if (filters.status) params.set("status", filters.status);
  }
  const qs = params.toString();
  return request<ListDocumentsResponse>(`/v1/documents${qs ? `?${qs}` : ""}`);
}

export async function getDocument(id: number): Promise<EditorDoc> {
  return request<EditorDoc>(`/v1/documents/${id}`);
}

export async function createDocument(body: DocumentInput): Promise<EditorDoc> {
  return request<EditorDoc>("/v1/documents", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateDocument(
  id: number,
  body: DocumentPartial,
): Promise<EditorDoc> {
  return request<EditorDoc>(`/v1/documents/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteDocument(id: number): Promise<void> {
  return request<void>(`/v1/documents/${id}`, { method: "DELETE" });
}

export async function restoreDocument(id: number): Promise<EditorDoc> {
  return request<EditorDoc>(`/v1/documents/${id}/restore`, { method: "POST" });
}

export async function permanentDeleteDocument(id: number): Promise<void> {
  return request<void>(`/v1/documents/${id}/permanent`, { method: "DELETE" });
}
