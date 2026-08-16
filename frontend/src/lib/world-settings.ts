/**
 * World-setting API client — nested under a document (novel).
 */
import {
  ApiError,
  type WorldSettingListItem,
  type WorldSettingRead,
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
      typeof detail === "string" ? detail : `请求失败 (${res.status})`;
    throw new ApiError(msg, res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface ListWorldSettingsResponse {
  items: WorldSettingListItem[];
  total: number;
}

export interface WorldSettingInput {
  category?: string;
  title: string;
  content_text?: string;
  metadata_json?: Record<string, unknown>;
}

export async function listWorldSettings(
  docId: number,
  opts?: { limit?: number },
): Promise<ListWorldSettingsResponse> {
  const limit = opts?.limit ?? 100;
  return request<ListWorldSettingsResponse>(
    `/v1/documents/${docId}/world-settings?limit=${limit}`,
  );
}

export async function getWorldSetting(
  docId: number,
  id: number,
): Promise<WorldSettingRead> {
  return request<WorldSettingRead>(
    `/v1/documents/${docId}/world-settings/${id}`,
  );
}

export async function createWorldSetting(
  docId: number,
  body: WorldSettingInput,
): Promise<WorldSettingRead> {
  return request<WorldSettingRead>(`/v1/documents/${docId}/world-settings`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateWorldSetting(
  docId: number,
  id: number,
  body: WorldSettingInput,
): Promise<WorldSettingRead> {
  return request<WorldSettingRead>(
    `/v1/documents/${docId}/world-settings/${id}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

export async function deleteWorldSetting(docId: number, id: number): Promise<void> {
  return request<void>(`/v1/documents/${docId}/world-settings/${id}`, {
    method: "DELETE",
  });
}
