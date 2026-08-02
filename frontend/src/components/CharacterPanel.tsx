"use client";

import { useCallback, useEffect, useState } from "react";

import {
  listCharacters,
  createCharacter,
  updateCharacter,
  deleteCharacter,
  getCharacter,
} from "@/lib/characters";
import type {
  CharacterListItem,
  CharacterRead,
  CharacterUpdate,
} from "@/lib/types";
import { CHARACTER_ROLE_OPTIONS } from "@/lib/types";

interface CharacterPanelProps {
  docId: number;
  onSelectChapter?: (chapterId: number) => void;
}

interface CharForm {
  name: string;
  role: string;
  description: string;
  arc_summary: string;
}

const EMPTY_FORM: CharForm = {
  name: "",
  role: "主角",
  description: "",
  arc_summary: "",
};

export function CharacterPanel({ docId }: CharacterPanelProps) {
  const [chars, setChars] = useState<CharacterListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<
    Record<number, CharacterRead>
  >({});

  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<CharForm>(EMPTY_FORM);

  const [editId, setEditId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<CharForm>(EMPTY_FORM);

  const [deletingId, setDeletingId] = useState<number | null>(null);

  // ---- Data fetching ----

  const fetchChars = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listCharacters(docId, 500);
      setChars(res.items);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [docId]);

  useEffect(() => {
    fetchChars();
  }, [fetchChars]);

  // Fetch full detail when expanding a card.
  useEffect(() => {
    if (expandedId == null) return;
    if (expandedDetail[expandedId]) return; // already fetched
    let cancelled = false;
    (async () => {
      try {
        const detail = await getCharacter(docId, expandedId);
        if (!cancelled) {
          setExpandedDetail((prev) => ({ ...prev, [expandedId]: detail }));
        }
      } catch {
        // silently ignore — expand will just show less info
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [expandedId, expandedDetail, docId]);

  // ---- Handlers ----

  const handleCreate = useCallback(async () => {
    try {
      await createCharacter(docId, {
        name: createForm.name,
        role: createForm.role,
        description: createForm.description || undefined,
        arc_summary: createForm.arc_summary || undefined,
      });
      setShowCreate(false);
      setCreateForm(EMPTY_FORM);
      await fetchChars();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    }
  }, [docId, createForm, fetchChars]);

  const handleUpdate = useCallback(async () => {
    if (editId == null) return;
    try {
      const body: CharacterUpdate = {
        name: editForm.name,
        role: editForm.role,
        description: editForm.description || undefined,
        arc_summary: editForm.arc_summary || undefined,
      };
      const updated = await updateCharacter(docId, editId, body);
      setExpandedDetail((prev) => ({ ...prev, [editId]: updated }));
      setEditId(null);
      setEditForm(EMPTY_FORM);
      await fetchChars();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    }
  }, [docId, editId, editForm, fetchChars]);

  const handleDelete = useCallback(
    async (charId: number) => {
      try {
        await deleteCharacter(docId, charId);
        setDeletingId(null);
        if (expandedId === charId) {
          setExpandedId(null);
          setExpandedDetail((prev) => {
            const next = { ...prev };
            delete next[charId];
            return next;
          });
        }
        await fetchChars();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      }
    },
    [docId, expandedId, fetchChars],
  );

  const handleToggleExpand = useCallback(
    (charId: number) => {
      setExpandedId((prev) => (prev === charId ? null : charId));
      // Exit edit mode when collapsing.
      if (expandedId === charId) {
        setEditId(null);
        setEditForm(EMPTY_FORM);
        setDeletingId(null);
      }
    },
    [expandedId],
  );

  const handleFormChange = useCallback(
    (field: keyof CharForm, setter: React.Dispatch<React.SetStateAction<CharForm>>) =>
      (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
        setter((prev) => ({ ...prev, [field]: e.target.value }));
      },
    [],
  );

  const handleStartEdit = useCallback(
    (charId: number) => {
      const detail = expandedDetail[charId];
      setEditId(charId);
      setEditForm({
        name: detail?.name ?? "",
        role: detail?.role ?? "主角",
        description: detail?.description ?? "",
        arc_summary: detail?.arc_summary ?? "",
      });
    },
    [expandedDetail],
  );

  // ---- Render helpers ----

  const renderForm = (
    form: CharForm,
    onSave: () => void,
    onCancel: () => void,
  ) => (
    <div
      className="flex flex-col gap-sp-2 p-sp-3 border-b"
      style={{ borderColor: "var(--border-hairline)" }}
    >
      <input
        type="text"
        value={form.name}
        onChange={handleFormChange("name", form === createForm ? setCreateForm : setEditForm)}
        placeholder="角色名称"
        className="w-full px-2 py-1 rounded text-[12px] outline-none border"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
          color: "var(--fg)",
        }}
      />
      <select
        value={form.role}
        onChange={handleFormChange("role", form === createForm ? setCreateForm : setEditForm)}
        className="w-full px-2 py-1 rounded text-[12px] outline-none border"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
          color: "var(--fg)",
        }}
      >
        {CHARACTER_ROLE_OPTIONS.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
      <textarea
        value={form.description}
        onChange={handleFormChange("description", form === createForm ? setCreateForm : setEditForm)}
        placeholder="角色描述"
        rows={2}
        className="w-full px-2 py-1 rounded text-[12px] outline-none border resize-none"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
          color: "var(--fg)",
        }}
      />
      <textarea
        value={form.arc_summary}
        onChange={handleFormChange("arc_summary", form === createForm ? setCreateForm : setEditForm)}
        placeholder="角色成长弧线"
        rows={2}
        className="w-full px-2 py-1 rounded text-[12px] outline-none border resize-none"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
          color: "var(--fg)",
        }}
      />
      <div className="flex gap-sp-2 justify-end">
        <button
          type="button"
          onClick={onCancel}
          className="px-2 py-0.5 rounded text-[11px] border transition-colors"
          style={{
            borderColor: "var(--border)",
            color: "var(--fg-secondary)",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--surface-2)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent";
          }}
        >
          取消
        </button>
        <button
          type="button"
          disabled={!form.name.trim()}
          onClick={onSave}
          className="px-2 py-0.5 rounded text-[11px] font-medium transition-opacity disabled:opacity-40"
          style={{
            background: "var(--accent)",
            color: "var(--bg)",
          }}
          onMouseEnter={(e) => {
            if (!e.currentTarget.disabled) {
              e.currentTarget.style.background = "var(--accent-hover)";
            }
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "var(--accent)";
          }}
        >
          保存
        </button>
      </div>
    </div>
  );

  return (
    <aside
      className="flex flex-col h-full overflow-hidden"
      style={{ background: "var(--bg)" }}
    >
      {/* Top bar */}
      <div
        className="px-sp-3 py-sp-2 border-b flex items-center gap-sp-2 shrink-0"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
        }}
      >
        <h3
          className="text-[12px] font-semibold flex-1"
          style={{ color: "var(--fg)" }}
        >
          👤 角色
        </h3>
        <button
          type="button"
          onClick={() => {
            setShowCreate((v) => !v);
            setCreateForm(EMPTY_FORM);
          }}
          className="px-2 py-0.5 rounded text-[11px] font-medium transition-opacity"
          style={{
            background: "var(--accent)",
            color: "var(--bg)",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--accent-hover)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "var(--accent)";
          }}
        >
          + 添加
        </button>
      </div>

      {/* Content */}
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

        {/* Error state */}
        {!loading && error && (
          <div className="p-sp-3 flex flex-col gap-sp-2">
            <p className="text-[11px]" style={{ color: "var(--danger)" }}>
              {error}
            </p>
            <button
              type="button"
              onClick={fetchChars}
              className="self-start px-2 py-0.5 rounded text-[11px] border transition-colors"
              style={{
                borderColor: "var(--border)",
                color: "var(--fg-secondary)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "var(--surface-2)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
              }}
            >
              重试
            </button>
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && chars.length === 0 && !showCreate && (
          <div className="p-sp-3">
            <p className="text-[11px]" style={{ color: "var(--muted)" }}>
              暂无角色
            </p>
          </div>
        )}

        {/* Create form */}
        {showCreate &&
          renderForm(createForm, handleCreate, () => {
            setShowCreate(false);
            setCreateForm(EMPTY_FORM);
          })}

        {/* Character list */}
        {!loading &&
          chars.map((ch) => {
            const isExpanded = ch.id === expandedId;
            const detail = expandedDetail[ch.id];
            const isEditing = ch.id === editId;
            const isDeleting = ch.id === deletingId;

            return (
              <div
                key={ch.id}
                className="border-b cursor-pointer"
                style={{ borderColor: "var(--border-hairline)" }}
                onClick={() => handleToggleExpand(ch.id)}
              >
                {/* Collapsed row */}
                <div className="p-sp-3 flex flex-col gap-sp-1">
                  <div className="flex items-center gap-sp-2">
                    <span
                      className="font-medium text-[13px] truncate"
                      style={{ color: "var(--fg)" }}
                    >
                      {ch.name}
                    </span>
                    <span
                      className="shrink-0 text-[9px] uppercase px-1 rounded"
                      style={{
                        background: "var(--surface-2)",
                        color: "var(--muted)",
                      }}
                    >
                      {ch.role}
                    </span>
                  </div>
                  {!isExpanded && detail?.description && (
                    <p
                      className="text-[10px] line-clamp-2 overflow-hidden"
                      style={{ color: "var(--muted)" }}
                    >
                      {detail.description}
                    </p>
                  )}
                </div>

                {/* Expanded content */}
                {isExpanded && (
                  <div
                    className="px-sp-3 pb-sp-3 flex flex-col gap-sp-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {/* Edit form or detail view */}
                    {isEditing
                      ? renderForm(editForm, handleUpdate, () => {
                          setEditId(null);
                          setEditForm(EMPTY_FORM);
                        })
                      : detail && (
                          <>
                            {detail.description && (
                              <p
                                className="text-[11px]"
                                style={{ color: "var(--fg-secondary)" }}
                              >
                                {detail.description}
                              </p>
                            )}
                            {detail.attributes &&
                              Object.keys(detail.attributes).length > 0 && (
                                <div className="flex flex-col gap-px">
                                  {Object.entries(detail.attributes).map(
                                    ([k, v]) => (
                                      <div
                                        key={k}
                                        className="text-[10px]"
                                        style={{
                                          color: "var(--fg-secondary)",
                                        }}
                                      >
                                        <span style={{ color: "var(--muted)" }}>
                                          {k}:
                                        </span>{" "}
                                        {String(v)}
                                      </div>
                                    ),
                                  )}
                                </div>
                              )}
                            {detail.arc_summary && (
                              <p
                                className="text-[11px]"
                                style={{ color: "var(--fg-secondary)" }}
                              >
                                {detail.arc_summary}
                              </p>
                            )}
                          </>
                        )}

                    {/* Delete confirmation */}
                    {isDeleting && (
                      <div className="flex flex-col gap-sp-1">
                        <p
                          className="text-[11px]"
                          style={{ color: "var(--danger)" }}
                        >
                          确认删除此角色？
                        </p>
                        <div className="flex gap-sp-2 justify-end">
                          <button
                            type="button"
                            onClick={() => setDeletingId(null)}
                            className="px-2 py-0.5 rounded text-[11px] border transition-colors"
                            style={{
                              borderColor: "var(--border)",
                              color: "var(--fg-secondary)",
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.background =
                                "var(--surface-2)";
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.background = "transparent";
                            }}
                          >
                            取消
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDelete(ch.id)}
                            className="px-2 py-0.5 rounded text-[11px] font-medium transition-opacity"
                            style={{
                              borderColor: "var(--danger)",
                              color: "var(--danger)",
                              border: "1px solid var(--danger)",
                              background: "transparent",
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.background =
                                "oklch(0.60 0.16 25 / 0.10)";
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.background = "transparent";
                            }}
                          >
                            确认
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Action buttons */}
                    {!isEditing && !isDeleting && (
                      <div className="flex gap-sp-2 justify-end">
                        <button
                          type="button"
                          onClick={() => handleStartEdit(ch.id)}
                          className="px-2 py-0.5 rounded text-[11px] border transition-colors"
                          style={{
                            borderColor: "var(--border)",
                            color: "var(--fg-secondary)",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background =
                              "var(--surface-2)";
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = "transparent";
                          }}
                        >
                          编辑
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeletingId(ch.id)}
                          className="px-2 py-0.5 rounded text-[11px] border transition-colors"
                          style={{
                            borderColor: "var(--border)",
                            color: "var(--fg-secondary)",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background =
                              "var(--surface-2)";
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = "transparent";
                          }}
                        >
                          删除
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
      </div>
    </aside>
  );
}
