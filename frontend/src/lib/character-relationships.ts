/**
 * Character relationship API client — nested under a document's characters
 * (R9-③). Endpoints (backend app/api/character_relationships.py):
 *   GET    /v1/documents/{docId}/characters/relationships/graph
 *   PUT    /v1/documents/{docId}/characters/relationships/{subjectId}/{objectId}
 *   DELETE /v1/documents/{docId}/characters/relationships/{subjectId}/{objectId}
 *   POST   /v1/documents/{docId}/characters/relationships/import
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

export interface RelationshipGraphNode {
  id: number;
  name: string;
  role: string;
}

export interface RelationshipGraphEdge {
  subject_id: number;
  object_id: number;
  relation_type: string;
  description: string;
  strength: number;
}

export interface RelationshipGraph {
  nodes: RelationshipGraphNode[];
  edges: RelationshipGraphEdge[];
}

export interface RelationshipImportItem {
  subject_name: string;
  object_name: string;
  relation_type?: string;
  description?: string;
  strength?: number;
}

export interface RelationshipImportResult {
  created: number;
  updated: number;
  skipped: number;
}

export async function fetchRelationshipGraph(
  docId: number,
): Promise<RelationshipGraph> {
  return request<RelationshipGraph>(
    `/v1/documents/${docId}/characters/relationships/graph`,
  );
}

export async function upsertRelationship(
  docId: number,
  subjectId: number,
  objectId: number,
  input: { relation_type: string; description?: string; strength?: number },
): Promise<RelationshipImportResult> {
  return request<RelationshipImportResult>(
    `/v1/documents/${docId}/characters/relationships/${subjectId}/${objectId}`,
    { method: "PUT", body: JSON.stringify(input) },
  );
}

export async function deleteRelationship(
  docId: number,
  subjectId: number,
  objectId: number,
): Promise<void> {
  await request(
    `/v1/documents/${docId}/characters/relationships/${subjectId}/${objectId}`,
    { method: "DELETE" },
  );
}

export async function importRelationships(
  docId: number,
  items: RelationshipImportItem[],
): Promise<RelationshipImportResult> {
  return request<RelationshipImportResult>(
    `/v1/documents/${docId}/characters/relationships/import`,
    { method: "POST", body: JSON.stringify({ items }) },
  );
}
