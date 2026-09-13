"use client";

/**
 * MemoryLibrary (R10-⑥): unified management UI for everything RAG retrieves
 * over — chapters, characters, world settings, plot events, relationships,
 * knowledge docs. Search/filter across all kinds, inline delete, knowledge
 * upload (file or pasted text). Creates/edits for the lore kinds jump to
 * the editor's dedicated panels (they own the forms); this page is the
 * at-a-glance library.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  deleteKnowledgeDoc,
  fetchAllMemoryRows,
  MEMORY_KIND_LABEL,
  uploadKnowledgeDoc,
  uploadKnowledgeText,
  type MemoryKind,
  type MemoryRow,
} from "@/lib/memory";

const KIND_ORDER: MemoryKind[] = [
  "chapter", "character", "world", "event", "relationship", "knowledge",
];

interface MemoryLibraryProps {
  docId: number;
}

export function MemoryLibrary({ docId }: MemoryLibraryProps) {
  const router = useRouter();
  const [rows, setRows] = useState<MemoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<"all" | MemoryKind>("all");
  const [busyId, setBusyId] = useState<string | number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [pasteTitle, setPasteTitle] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 3500);
  }, []);

  const reload = useCallback(async () => {
    setError(null);
    try {
      setRows(await fetchAllMemoryRows(docId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载记忆库失败");
    }
  }, [docId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const filtered = useMemo(() => {
    if (!rows) return [];
    let list = rows;
    if (kindFilter !== "all") list = list.filter((r) => r.kind === kindFilter);
    const q = query.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (r) => r.title.toLowerCase().includes(q) || r.preview.toLowerCase().includes(q),
      );
    }
    return list;
  }, [rows, kindFilter, query]);

  const counts = useMemo(() => {
    const by = {} as Record<MemoryKind, number>;
    for (const r of rows ?? []) by[r.kind] = (by[r.kind] ?? 0) + 1;
    return by;
  }, [rows]);

  const handleDelete = useCallback(async (row: MemoryRow) => {
    if (!window.confirm(`删除「${row.title}」？删除后不再进入 RAG 检索。`)) return;
    setBusyId(row.id);
    try {
      if (row.kind === "knowledge") {
        await deleteKnowledgeDoc(docId, String(row.id));
      } else {
        // Delegate per-kind delete to the existing lib endpoints.
        const mods = await Promise.all([
          import("@/lib/chapters"),
          import("@/lib/characters"),
          import("@/lib/world-settings"),
          import("@/lib/plot-events"),
          import("@/lib/character-relationships"),
        ]);
        const [chapters, characters, worlds, events, rels] = mods;
        const id = Number(row.id);
        switch (row.kind) {
          case "chapter": await chapters.deleteChapter(docId, id); break;
          case "character": await characters.deleteCharacter(docId, id); break;
          case "world": await worlds.deleteWorldSetting(docId, id); break;
          case "event": await events.deletePlotEvent(docId, id); break;
          case "relationship":
            await rels.deleteRelationship(
              docId,
              Number(row.subjectId),
              Number(row.objectId),
            );
            break;
        }
      }
      setRows((prev) => prev?.filter((r) => !(r.kind === row.kind && r.id === row.id)) ?? prev);
      showToast("已删除");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusyId(null);
    }
  }, [docId, showToast]);

  const handleUploadFile = useCallback(async (file: File) => {
    setUploading(true);
    try {
      await uploadKnowledgeDoc(docId, file);
      showToast(`已上传 ${file.name}（后台分块+索引中）`);
      await reload();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }, [docId, reload, showToast]);

  const handleUploadText = useCallback(async () => {
    const title = pasteTitle.trim();
    const text = pasteText.trim();
    if (!title || !text) return;
    setUploading(true);
    try {
      await uploadKnowledgeText(docId, title, text);
      setPasteTitle("");
      setPasteText("");
      setUploadOpen(false);
      showToast("已保存为知识文档（后台分块+索引中）");
      await reload();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "保存失败");
    } finally {
      setUploading(false);
    }
  }, [docId, pasteTitle, pasteText, reload, showToast]);

  if (rows === null && !error) {
    return (
      <div className="px-sp-5 py-sp-6 text-[13px]" style={{ color: "var(--muted)" }}>
        加载记忆库…
      </div>
    );
  }
  if (error) {
    return (
      <div className="px-sp-5 py-sp-6 text-[13px] flex flex-col gap-sp-2" style={{ color: "var(--danger)" }}>
        {error}
        <button
          type="button"
          onClick={() => void reload()}
          className="self-start px-sp-3 py-sp-1 rounded-sm text-[12px] border"
          style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
        >
          重试
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-sp-3">
      {/* Toolbar: search + kind filter + knowledge upload */}
      <div className="flex flex-wrap items-center gap-sp-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索标题或内容…"
          className="px-sp-3 py-sp-1.5 rounded-sm border text-[12px] outline-none min-w-[180px] flex-1"
          style={{
            background: "var(--surface)",
            borderColor: "var(--border-subtle)",
            color: "var(--fg)",
          }}
        />
        <button
          type="button"
          onClick={() => setUploadOpen((v) => !v)}
          className="px-sp-3 py-sp-1.5 rounded-sm text-[12px] font-medium border transition-colors shrink-0"
          style={{
            borderColor: "var(--accent)",
            color: uploadOpen ? "var(--bg)" : "var(--accent)",
            background: uploadOpen ? "var(--accent)" : "transparent",
          }}
        >
          + 知识文档
        </button>
      </div>

      {/* Kind filter chips */}
      <div className="flex flex-wrap gap-sp-1">
        <button
          type="button"
          onClick={() => setKindFilter("all")}
          className="px-2 py-0.5 rounded-full text-[10px] transition-colors"
          style={
            kindFilter === "all"
              ? { background: "var(--accent)", color: "#fff" }
              : { border: "1px solid var(--border-hairline)", color: "var(--fg-tertiary)" }
          }
        >
          全部 {rows?.length ?? 0}
        </button>
        {KIND_ORDER.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setKindFilter(k)}
            className="px-2 py-0.5 rounded-full text-[10px] transition-colors"
            style={
              kindFilter === k
                ? { background: "var(--accent)", color: "#fff" }
                : { border: "1px solid var(--border-hairline)", color: "var(--fg-tertiary)" }
            }
          >
            {MEMORY_KIND_LABEL[k]} {counts[k] ?? 0}
          </button>
        ))}
      </div>

      {/* Knowledge upload panel */}
      {uploadOpen && (
        <div
          className="rounded-md p-sp-3 flex flex-col gap-sp-2"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border-subtle)" }}
        >
          <div className="flex gap-sp-2">
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.md,.markdown,text/plain"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void handleUploadFile(f);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              disabled={uploading}
              onClick={() => fileRef.current?.click()}
              className="px-sp-3 py-sp-1.5 rounded-sm text-[12px] border transition-colors disabled:opacity-40"
              style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
            >
              📄 选择文件（txt/md）
            </button>
          </div>
          <div className="flex items-center gap-sp-2 text-[10px]" style={{ color: "var(--muted)" }}>
            <span className="flex-1" style={{ height: 1, background: "var(--border-hairline)" }} />
            或粘贴文本
            <span className="flex-1" style={{ height: 1, background: "var(--border-hairline)" }} />
          </div>
          <input
            type="text"
            value={pasteTitle}
            onChange={(e) => setPasteTitle(e.target.value)}
            placeholder="标题（如：力量体系补充设定）"
            className="px-sp-3 py-sp-1.5 rounded-sm border text-[12px] outline-none"
            style={{ background: "var(--surface)", borderColor: "var(--border-subtle)", color: "var(--fg)" }}
          />
          <textarea
            rows={4}
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            placeholder="粘贴要入库的设定/资料文本…"
            className="px-sp-3 py-sp-1.5 rounded-sm border text-[12px] outline-none resize-none"
            style={{ background: "var(--surface)", borderColor: "var(--border-subtle)", color: "var(--fg)" }}
          />
          <div className="flex justify-end">
            <button
              type="button"
              disabled={uploading || !pasteTitle.trim() || !pasteText.trim()}
              onClick={() => void handleUploadText()}
              className="px-sp-4 py-sp-1.5 rounded-sm text-[12px] font-medium border transition-colors disabled:opacity-40"
              style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
            >
              {uploading ? "处理中…" : "保存入库"}
            </button>
          </div>
        </div>
      )}

      {/* Rows table */}
      <div className="rounded-md overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
        {filtered.length === 0 ? (
          <div className="px-sp-4 py-sp-6 text-center text-[12px]" style={{ color: "var(--muted)" }}>
            {rows?.length ? "没有匹配的记忆条目" : "记忆库为空——写章节、添加人物/设定后自动入库"}
          </div>
        ) : (
          filtered.map((row) => (
            <div
              key={`${row.kind}-${row.id}`}
              className="px-sp-4 py-sp-2 flex items-center gap-sp-3 border-b last:border-b-0"
              style={{ borderColor: "var(--border-hairline)" }}
            >
              <span
                className="shrink-0 text-[9px] uppercase px-1.5 py-px rounded"
                style={{ background: "var(--surface-2)", color: "var(--muted)" }}
              >
                {MEMORY_KIND_LABEL[row.kind]}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[12px] font-medium truncate" style={{ color: "var(--fg)" }}>
                  {row.title}
                </div>
                {row.preview && (
                  <div className="text-[10px] truncate" style={{ color: "var(--muted)" }}>
                    {row.preview}
                  </div>
                )}
              </div>
              {row.badge && (
                <span className="shrink-0 text-[10px]" style={{ color: "var(--fg-tertiary)" }}>
                  {row.badge}
                </span>
              )}
              {/* Edit: jump to the owning panel in the editor */}
              {row.kind !== "knowledge" && row.kind !== "relationship" && (
                <button
                  type="button"
                  onClick={() => router.push(`/novels/${docId}/editor`)}
                  className="shrink-0 text-[10px] px-sp-2 py-px rounded-sm border transition-colors"
                  style={{ borderColor: "var(--border-hairline)", color: "var(--fg-secondary)" }}
                  title="在编辑器中编辑"
                >
                  编辑
                </button>
              )}
              {row.kind === "relationship" && (
                <button
                  type="button"
                  onClick={() => router.push(`/novels/${docId}/graph?tab=graph`)}
                  className="shrink-0 text-[10px] px-sp-2 py-px rounded-sm border transition-colors"
                  style={{ borderColor: "var(--border-hairline)", color: "var(--fg-secondary)" }}
                  title="在关系图中调整"
                >
                  调整
                </button>
              )}
              <button
                type="button"
                disabled={busyId === row.id}
                onClick={() => void handleDelete(row)}
                className="shrink-0 text-[10px] px-sp-2 py-px rounded-sm border transition-colors disabled:opacity-40"
                style={{ borderColor: "oklch(0.60 0.16 25 / 0.35)", color: "var(--danger)" }}
              >
                {busyId === row.id ? "…" : "删除"}
              </button>
            </div>
          ))
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div
          className="fixed bottom-6 right-6 px-sp-4 py-sp-2 rounded-md text-[12px] shadow-lg z-50"
          style={{ background: "var(--surface)", border: "1px solid var(--border-subtle)", color: "var(--fg)" }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}
