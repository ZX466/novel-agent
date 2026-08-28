/**
 * Character API client — nested under a document (novel).
 */
import {
  ApiError,
  type CharacterListItem,
  type CharacterRead,
  type CharacterUpdate,
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

export interface ListCharactersResponse {
  items: CharacterListItem[];
  total: number;
}

export interface CharacterInput {
  name: string;
  role?: string;
  description?: string;
  attributes?: Record<string, unknown>;
  arc_summary?: string;
}

export async function listCharacters(
  docId: number,
  limit = 100,
): Promise<ListCharactersResponse> {
  return request<ListCharactersResponse>(
    `/v1/documents/${docId}/characters?limit=${limit}`,
  );
}

export async function getCharacter(
  docId: number,
  charId: number,
): Promise<CharacterRead> {
  return request<CharacterRead>(`/v1/documents/${docId}/characters/${charId}`);
}

export async function createCharacter(
  docId: number,
  body: CharacterInput,
): Promise<CharacterRead> {
  return request<CharacterRead>(`/v1/documents/${docId}/characters`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateCharacter(
  docId: number,
  charId: number,
  body: CharacterUpdate,
): Promise<CharacterRead> {
  return request<CharacterRead>(
    `/v1/documents/${docId}/characters/${charId}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

export async function deleteCharacter(docId: number, charId: number): Promise<void> {
  return request<void>(`/v1/documents/${docId}/characters/${charId}`, {
    method: "DELETE",
  });
}
