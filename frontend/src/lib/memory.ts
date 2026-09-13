/**
 * Memory library (R10-⑥): aggregated read/write access to everything RAG
 * retrieves over — chapters, characters, world settings, plot events,
 * character relationships, and knowledge docs. One lib so the /memory page
 * can list, create, edit, and delete across all six kinds.
 *
 * Reuses the existing per-kind clients where they exist (characters,
 * world settings, plot events, relationships); adds the missing knowledge
 * docs client. The list APIs are all cheap (limit-capped, no embeddings in
 * list shapes).
 */
import { ApiError } from "@/lib/types";
import { backendUrl } from "@/lib/config";
import { embeddingProviderHeaders, ownerAuthHeaders } from "@/lib/settings";
import { listChapters } from "@/lib/chapters";
import { listCharacters } from "@/lib/characters";
import { listWorldSettings } from "@/lib/world-settings";
import { listPlotEvents } from "@/lib/plot-events";
import { fetchRelationshipGraph } from "@/lib/character-relationships";

// ── Knowledge docs (no frontend client existed) ─────────────────────────

export interface KnowledgeFileSummary {
  title: string;
  chunk_count: number;
  created_at: string;
}

async function knowledgeRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${backendUrl}${path}`, {
    ...init,
    headers: {
      ...(init?.headers as Record<string, string> | undefined),
      ...ownerAuthHeaders(),
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

export function listKnowledgeDocs(docId: number): Promise<{ items: KnowledgeFileSummary[]; total: number }> {
  return knowledgeRequest(`/v1/documents/${docId}/knowledge-docs?limit=500`);
}

/** Upload a text file (txt/md) via multipart — the backend validates size/
 *  binary/rate limits and chunks+embeds server-side. */
export function uploadKnowledgeDoc(docId: number, file: File): Promise<unknown> {
  const form = new FormData();
  form.append("file", file, file.name);
  return knowledgeRequest(`/v1/documents/${docId}/knowledge-docs`, {
    method: "POST",
    body: form,
  });
}

/** Paste-in text → upload as a .txt file (same server path). */
export function uploadKnowledgeText(docId: number, title: string, text: string): Promise<unknown> {
  const filename = /\.(txt|md|markdown)$/i.test(title) ? title : `${title}.txt`;
  const form = new FormData();
  form.append("file", new File([text], filename, { type: "text/plain" }), filename);
  return knowledgeRequest(`/v1/documents/${docId}/knowledge-docs`, {
    method: "POST",
    body: form,
  });
}

export function deleteKnowledgeDoc(docId: number, title: string): Promise<void> {
  return knowledgeRequest<void>(
    `/v1/documents/${docId}/knowledge-docs/${encodeURIComponent(title)}`,
    { method: "DELETE" },
  );
}

// ── Unified memory row (library table model) ────────────────────────────

export type MemoryKind =
  | "chapter"
  | "character"
  | "world"
  | "event"
  | "relationship"
  | "knowledge";

export const MEMORY_KIND_LABEL: Record<MemoryKind, string> = {
  chapter: "章节",
  character: "人物",
  world: "世界观",
  event: "剧情事件",
  relationship: "人物关系",
  knowledge: "知识文档",
};

export interface MemoryRow {
  kind: MemoryKind;
  /** Stable identity for edit/delete routing (per-kind id scheme). */
  id: number | string;
  title: string;
  /** One-line preview of the body text that feeds RAG. */
  preview: string;
  /** Shows up as a chip (章节 3 / 主角 / 起承转合 / 关系强度…). */
  badge: string;
  updatedAt: string;
  /** Relationship rows only: the endpoint deletes by (subject, object). */
  subjectId?: number;
  objectId?: number;
}

/** Aggregate all six kinds into sortable, filterable rows. Promise.all —
 *  one panel load, five cheap list calls + one graph call. A failed kind
 *  degrades to an empty list for that kind (never blocks the page). */
export async function fetchAllMemoryRows(docId: number): Promise<MemoryRow[]> {
  const [chapters, chars, worlds, events, graph, knowledge] = await Promise.all([
    listChapters(docId, 500).then((r) => r.items).catch(() => []),
    listCharacters(docId, 500).then((r) => r.items).catch(() => []),
    listWorldSettings(docId, { limit: 500 }).then((r) => r.items).catch(() => []),
    listPlotEvents(docId, { limit: 500 }).then((r) => r.items).catch(() => []),
    fetchRelationshipGraph(docId).catch(() => ({ nodes: [], edges: [] })),
    listKnowledgeDocs(docId).then((r) => r.items).catch(() => []),
  ]);

  const rows: MemoryRow[] = [];
  for (const ch of chapters) {
    rows.push({
      kind: "chapter",
      id: ch.id,
      title: ch.title,
      preview: (ch.content_text || "").slice(0, 80),
      badge: `第${ch.chapter_index}章`,
      updatedAt: ch.updated_at,
    });
  }
  for (const c of chars) {
    rows.push({
      kind: "character",
      id: c.id,
      title: c.name,
      preview: c.description || c.arc_summary || "",
      badge: c.role,
      updatedAt: c.updated_at,
    });
  }
  for (const w of worlds) {
    rows.push({
      kind: "world",
      id: w.id,
      title: w.title,
      preview: (w as { content_text?: string }).content_text?.slice(0, 80) ?? "",
      badge: w.category,
      updatedAt: w.updated_at,
    });
  }
  for (const e of events) {
    rows.push({
      kind: "event",
      id: e.id,
      title: e.summary.slice(0, 40),
      preview: e.summary,
      badge: e.chapter_index != null ? `第${e.chapter_index}章 · ${e.event_type}` : e.event_type,
      updatedAt: e.updated_at,
    });
  }
  const nameById = new Map<number, string>(
    (graph as { nodes: Array<{ id: number; name: string }> }).nodes.map((n) => [n.id, n.name]),
  );
  for (const e of (graph as { edges: Array<{ id: number; subject_id: number; object_id: number; relation_type: string; strength: number }> }).edges) {
    const a = nameById.get(e.subject_id) ?? `#${e.subject_id}`;
    const b = nameById.get(e.object_id) ?? `#${e.object_id}`;
    rows.push({
      kind: "relationship",
      id: e.id,
      title: `${a} — ${e.relation_type || "关系"} — ${b}`,
      preview: `强度 ${e.strength}`,
      badge: "关系",
      updatedAt: "",
      subjectId: e.subject_id,
      objectId: e.object_id,
    });
  }
  for (const k of knowledge) {
    rows.push({
      kind: "knowledge",
      id: k.title,
      title: k.title,
      preview: `${k.chunk_count} 个分块`,
      badge: "知识文档",
      updatedAt: k.created_at,
    });
  }
  return rows;
}

/** Re-export for the page's "添加" flows (panels own the create forms, but
 *  the memory page offers quick-add for the three lore kinds). */
export { embeddingProviderHeaders };
