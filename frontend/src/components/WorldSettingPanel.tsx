"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createWorldSetting,
  deleteWorldSetting,
  listWorldSettings,
  updateWorldSetting,
} from "@/lib/world-settings";
import type {
  WorldSettingCreate,
  WorldSettingListItem,
  WorldSettingRead,
} from "@/lib/types";
import { WORLD_CATEGORY_OPTIONS } from "@/lib/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WorldSettingPanelProps {
  docId: number;
}

type FormData = {
  category: string;
  title: string;
  content_text: string;
};

const EMPTY_FORM: FormData = {
  category: "其他",
  title: "",
  content_text: "",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function WorldSettingPanel({ docId }: WorldSettingPanelProps) {
  // List state
  const [items, setItems] = useState<WorldSettingListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter
  const [selectedCategory, setSelectedCategory] = useState("全部");

  // Expand / edit / delete
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<
    Record<number, WorldSettingRead>
  >({});
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<FormData>({ ...EMPTY_FORM });
  const [editId, setEditId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<FormData>({ ...EMPTY_FORM });
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  // ---- Fetch list ----
  const fetchList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listWorldSettings(docId, { limit: 500 });
      setItems(res.items);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [docId]);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  // ---- Filtered list ----
  const filtered = useMemo(
    () =>
      selectedCategory === "全部"
        ? items
        : items.filter((i) => i.category === selectedCategory),
    [items, selectedCategory],
  );

  // ---- Expand / collapse ----
  const handleToggleExpand = useCallback(
    async (id: number) => {
      if (expandedId === id) {
        setExpandedId(null);
        return;
      }
      setExpandedId(id);
      if (!expandedDetail[id]) {
        try {
          // find the item to get its category for placeholder
          const item = items.find((i) => i.id === id);
          // We need the full content, fetch via listWorldSettings category filter
          // but the list doesn't include content_text. Fetch individually.
          const { getWorldSetting } = await import("@/lib/world-settings");
          const detail = await getWorldSetting(docId, id);
          setExpandedDetail((prev) => ({ ...prev, [id]: detail }));
        } catch {
          // silently ignore; expanded area will show "加载失败"
        }
      }
    },
    [expandedId, expandedDetail, items, docId],
  );

  // ---- Create ----
  const handleCreate = useCallback(async () => {
    if (!createForm.title.trim()) return;
    setSaving(true);
    try {
      const body: WorldSettingCreate = {
        category: createForm.category,
        title: createForm.title.trim(),
        content_text: createForm.content_text || undefined,
      };
      await createWorldSetting(docId, body);
      setShowCreate(false);
      setCreateForm({ ...EMPTY_FORM });
      await fetchList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setSaving(false);
    }
  }, [createForm, docId, fetchList]);

  // ---- Edit ----
  const handleStartEdit = useCallback(
    async (item: WorldSettingListItem) => {
      setEditId(item.id);
      // Try to use cached detail; otherwise fetch
      let detail = expandedDetail[item.id];
      if (!detail) {
        try {
          const { getWorldSetting } = await import("@/lib/world-settings");
          detail = await getWorldSetting(docId, item.id);
          setExpandedDetail((prev) => ({ ...prev, [item.id]: detail! }));
        } catch {
          // fallback with what we have
        }
      }
      setEditForm({
        category: detail?.category ?? item.category,
        title: detail?.title ?? item.title,
        content_text: detail?.content_text ?? "",
      });
    },
    [expandedDetail, docId],
  );

  const handleSaveEdit = useCallback(async () => {
    if (editId == null || !editForm.title.trim()) return;
    setSaving(true);
    try {
      const body: WorldSettingCreate = {
        category: editForm.category,
        title: editForm.title.trim(),
        content_text: editForm.content_text || undefined,
      };
      await updateWorldSetting(docId, editId, body);
      setEditId(null);
      setExpandedDetail((prev) => {
        const next = { ...prev };
        delete next[editId];
        return next;
      });
      await fetchList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }, [editId, editForm, docId, fetchList]);

  // ---- Delete ----
  const handleDelete = useCallback(
    async (id: number) => {
      try {
        await deleteWorldSetting(docId, id);
        setDeletingId(null);
        if (expandedId === id) setExpandedId(null);
        setExpandedDetail((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
        await fetchList();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "删除失败");
      }
    },
    [docId, expandedId, fetchList],
  );

  // ---- Category chips ----
  const allCategories = useMemo(
    () => ["全部", ...WORLD_CATEGORY_OPTIONS],
    [],
  );

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  return (
    <aside
      className="flex flex-col h-full overflow-hidden"
      style={{ width: 200, background: "var(--bg)" }}
    >
      {/* Header */}
      <div
        className="px-sp-3 py-sp-2 border-b flex items-center gap-sp-2 shrink-0"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
        }}
      >
        <h3
          className="text-[11px] font-semibold flex-1"
          style={{ color: "var(--fg-secondary)" }}
        >
          🌍 世界观
        </h3>
        <button
          type="button"
          onClick={() => setShowCreate((v) => !v)}
          className="px-sp-2 py-px rounded text-[10px] font-medium border transition-colors"
          style={{
            borderColor: "var(--border-hairline)",
            color: showCreate ? "var(--muted)" : "var(--accent)",
            background: showCreate ? "var(--surface-2)" : "transparent",
          }}
        >
          + 添加
        </button>
      </div>

      {/* Category chips */}
      <div
        className="flex gap-sp-1 px-sp-2 py-sp-1.5 overflow-x-auto shrink-0"
        style={{ borderBottom: "1px solid var(--border-hairline)" }}
      >
        {allCategories.map((cat) => {
          const active = selectedCategory === cat;
          return (
            <button
              key={cat}
              type="button"
              onClick={() => setSelectedCategory(cat)}
              className="px-2 py-0.5 rounded-full text-[10px] whitespace-nowrap shrink-0 transition-colors"
              style={
                active
                  ? { background: "var(--accent)", color: "#fff" }
                  : {
                      border: "1px solid var(--border-hairline)",
                      color: "var(--fg-tertiary)",
                      background: "transparent",
                    }
              }
            >
              {cat}
            </button>
          );
        })}
      </div>

      {/* Error banner */}
      {error && (
        <div
          className="px-sp-3 py-sp-1.5 text-[10px] flex items-center gap-sp-1"
          style={{
            background: "oklch(0.60 0.16 25 / 0.08)",
            color: "var(--danger)",
          }}
        >
          <span className="flex-1 truncate">{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="shrink-0 text-[10px]"
          >
            ✕
          </button>
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div
          className="px-sp-3 py-sp-2 border-b space-y-sp-2 shrink-0"
          style={{ borderColor: "var(--border-hairline)" }}
        >
          <select
            value={createForm.category}
            onChange={(e) =>
              setCreateForm((f) => ({ ...f, category: e.target.value }))
            }
            className="w-full text-[11px] rounded px-sp-2 py-px border outline-none"
            style={{
              background: "var(--surface)",
              color: "var(--fg)",
              borderColor: "var(--border-hairline)",
            }}
          >
            {WORLD_CATEGORY_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="标题 (必填)"
            value={createForm.title}
            onChange={(e) =>
              setCreateForm((f) => ({ ...f, title: e.target.value }))
            }
            className="w-full text-[11px] rounded px-sp-2 py-px border outline-none"
            style={{
              background: "var(--surface)",
              color: "var(--fg)",
              borderColor: "var(--border-hairline)",
            }}
          />
          <textarea
            placeholder="内容"
            rows={4}
            value={createForm.content_text}
            onChange={(e) =>
              setCreateForm((f) => ({ ...f, content_text: e.target.value }))
            }
            className="w-full text-[11px] rounded px-sp-2 py-px border outline-none resize-none"
            style={{
              background: "var(--surface)",
              color: "var(--fg)",
              borderColor: "var(--border-hairline)",
            }}
          />
          <div className="flex gap-sp-2 justify-end">
            <button
              type="button"
              onClick={() => {
                setShowCreate(false);
                setCreateForm({ ...EMPTY_FORM });
              }}
              className="px-sp-2 py-px text-[10px] rounded border"
              style={{
                borderColor: "var(--border-hairline)",
                color: "var(--fg-tertiary)",
              }}
            >
              取消
            </button>
            <button
              type="button"
              disabled={saving || !createForm.title.trim()}
              onClick={handleCreate}
              className="px-sp-2 py-px text-[10px] rounded font-medium"
              style={{
                background: "var(--accent)",
                color: "#fff",
                opacity: saving || !createForm.title.trim() ? 0.5 : 1,
              }}
            >
              保存
            </button>
          </div>
        </div>
      )}

      {/* List */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {/* Loading skeleton */}
        {loading && (
          <div className="p-sp-3 space-y-sp-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-[14px] rounded-[3px]"
                style={{
                  background:
                    "linear-gradient(90deg, var(--surface) 25%, var(--surface-2) 50%, var(--surface) 75%)",
                  backgroundSize: "200% 100%",
                  animation: "shimmer 1.8s infinite",
                  width: i === 0 ? "50%" : i === 1 ? "85%" : "60%",
                }}
              />
            ))}
          </div>
        )}

        {/* Empty */}
        {!loading && filtered.length === 0 && (
          <div
            className="flex flex-col items-center p-sp-6 text-center gap-sp-2"
            style={{ color: "var(--muted)" }}
          >
            <p className="text-[12px]">
              {items.length === 0 ? "暂无世界观设定" : "该分类暂无设定"}
            </p>
            {items.length === 0 && (
              <button
                type="button"
                onClick={() => setShowCreate(true)}
                className="px-sp-3 py-sp-1 rounded-sm text-[11px] font-medium border transition-colors"
                style={{
                  borderColor: "var(--border)",
                  color: "var(--fg-secondary)",
                }}
              >
                + 添加第一条
              </button>
            )}
          </div>
        )}

        {/* Items */}
        {!loading &&
          filtered.map((item) => {
            const expanded = expandedId === item.id;
            const detail = expandedDetail[item.id];
            const isEditing = editId === item.id;
            const isDeleting = deletingId === item.id;

            return (
              <div
                key={item.id}
                className="px-sp-3 py-sp-3 border-b"
                style={{ borderColor: "var(--border-hairline)" }}
              >
                {/* Edit mode */}
                {isEditing ? (
                  <div className="space-y-sp-2">
                    <select
                      value={editForm.category}
                      onChange={(e) =>
                        setEditForm((f) => ({
                          ...f,
                          category: e.target.value,
                        }))
                      }
                      className="w-full text-[11px] rounded px-sp-2 py-px border outline-none"
                      style={{
                        background: "var(--surface)",
                        color: "var(--fg)",
                        borderColor: "var(--border-hairline)",
                      }}
                    >
                      {WORLD_CATEGORY_OPTIONS.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                    <input
                      type="text"
                      value={editForm.title}
                      onChange={(e) =>
                        setEditForm((f) => ({
                          ...f,
                          title: e.target.value,
                        }))
                      }
                      className="w-full text-[11px] rounded px-sp-2 py-px border outline-none"
                      style={{
                        background: "var(--surface)",
                        color: "var(--fg)",
                        borderColor: "var(--border-hairline)",
                      }}
                    />
                    <textarea
                      rows={4}
                      value={editForm.content_text}
                      onChange={(e) =>
                        setEditForm((f) => ({
                          ...f,
                          content_text: e.target.value,
                        }))
                      }
                      className="w-full text-[11px] rounded px-sp-2 py-px border outline-none resize-none"
                      style={{
                        background: "var(--surface)",
                        color: "var(--fg)",
                        borderColor: "var(--border-hairline)",
                      }}
                    />
                    <div className="flex gap-sp-2 justify-end">
                      <button
                        type="button"
                        onClick={() => setEditId(null)}
                        className="px-sp-2 py-px text-[10px] rounded border"
                        style={{
                          borderColor: "var(--border-hairline)",
                          color: "var(--fg-tertiary)",
                        }}
                      >
                        取消
                      </button>
                      <button
                        type="button"
                        disabled={saving || !editForm.title.trim()}
                        onClick={handleSaveEdit}
                        className="px-sp-2 py-px text-[10px] rounded font-medium"
                        style={{
                          background: "var(--accent)",
                          color: "#fff",
                          opacity:
                            saving || !editForm.title.trim() ? 0.5 : 1,
                        }}
                      >
                        保存
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    {/* Category chip + title */}
                    <div className="flex items-start gap-sp-1.5">
                      <span
                        className="text-[9px] uppercase px-1 rounded shrink-0 mt-px"
                        style={{
                          background: "var(--surface-2)",
                          color: "var(--muted)",
                        }}
                      >
                        {item.category}
                      </span>
                      <span
                        className="text-[12px] font-medium cursor-pointer flex-1 min-w-0"
                        style={{ color: "var(--fg)" }}
                        onClick={() => handleToggleExpand(item.id)}
                      >
                        {item.title}
                      </span>
                    </div>

                    {/* Preview */}
                    {!expanded && detail?.content_text && (
                      <p
                        className="text-[10px] mt-sp-1 line-clamp-2 cursor-pointer"
                        style={{ color: "var(--muted)" }}
                        onClick={() => handleToggleExpand(item.id)}
                      >
                        {detail.content_text}
                      </p>
                    )}
                    {!expanded && !detail?.content_text && (
                      <p
                        className="text-[10px] mt-sp-1 line-clamp-2 cursor-pointer"
                        style={{ color: "var(--muted)" }}
                        onClick={() => handleToggleExpand(item.id)}
                      >
                        {item.title}
                      </p>
                    )}

                    {/* Expanded full content */}
                    {expanded && (
                      <div className="mt-sp-2">
                        {detail?.content_text ? (
                          <p
                            className="text-[11px] max-h-40 overflow-y-auto"
                            style={{
                              color: "var(--fg-secondary)",
                              whiteSpace: "pre-wrap",
                            }}
                          >
                            {detail.content_text}
                          </p>
                        ) : (
                          <p
                            className="text-[11px] italic"
                            style={{ color: "var(--muted)" }}
                          >
                            无内容
                          </p>
                        )}

                        {/* Footer buttons */}
                        <div className="flex gap-sp-2 mt-sp-2 justify-end">
                          {isDeleting ? (
                            <>
                              <span
                                className="text-[10px] mr-auto"
                                style={{ color: "var(--danger)" }}
                              >
                                确认删除？
                              </span>
                              <button
                                type="button"
                                onClick={() => handleDelete(item.id)}
                                className="px-sp-2 py-px text-[10px] rounded font-medium"
                                style={{
                                  background: "var(--danger)",
                                  color: "#fff",
                                }}
                              >
                                确认
                              </button>
                              <button
                                type="button"
                                onClick={() => setDeletingId(null)}
                                className="px-sp-2 py-px text-[10px] rounded border"
                                style={{
                                  borderColor: "var(--border-hairline)",
                                  color: "var(--fg-tertiary)",
                                }}
                              >
                                取消
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                type="button"
                                onClick={() => handleStartEdit(item)}
                                className="px-sp-2 py-px text-[10px] rounded border transition-colors"
                                style={{
                                  borderColor: "var(--border-hairline)",
                                  color: "var(--fg-secondary)",
                                }}
                              >
                                编辑
                              </button>
                              <button
                                type="button"
                                onClick={() => setDeletingId(item.id)}
                                className="px-sp-2 py-px text-[10px] rounded border transition-colors"
                                style={{
                                  borderColor: "var(--border-hairline)",
                                  color: "var(--danger)",
                                }}
                              >
                                删除
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          })}
      </div>
    </aside>
  );
}
