"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import {
  listPlotEvents,
  getPlotEvent,
  createPlotEvent,
  updatePlotEvent,
  deletePlotEvent,
} from "@/lib/plot-events";
import type {
  PlotEventListItem,
  PlotEventRead,
} from "@/lib/types";
import { PLOT_EVENT_TYPE_OPTIONS } from "@/lib/types";

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

interface PlotEventPanelProps {
  docId: number;
  chapters: Array<{ id: number; chapter_index: number; title: string }>;
  onSelectChapter?: (chapterId: number) => void;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

interface CreateForm {
  chapter_index: string; // "" = unlinked, otherwise numeric string
  event_type: string;
  summary: string;
  involved_character_ids: string; // comma-separated
}

interface EditForm extends CreateForm {}

const EMPTY_FORM: CreateForm = {
  chapter_index: "",
  event_type: PLOT_EVENT_TYPE_OPTIONS[0],
  summary: "",
  involved_character_ids: "",
};

function toPayload(form: CreateForm) {
  return {
    chapter_index: form.chapter_index === "" ? null : Number(form.chapter_index),
    event_type: form.event_type,
    summary: form.summary,
    involved_character_ids: form.involved_character_ids
      .split(",")
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !isNaN(n)),
  };
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function PlotEventPanel({
  docId,
  chapters,
  onSelectChapter,
}: PlotEventPanelProps) {
  /* ---- state ---- */
  const [events, setEvents] = useState<PlotEventListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [chapterFilter, setChapterFilter] = useState<"all" | number>("all");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<PlotEventRead | null>(null);
  const [expandedLoading, setExpandedLoading] = useState(false);

  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<CreateForm>({ ...EMPTY_FORM });

  const [editId, setEditId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<EditForm>({ ...EMPTY_FORM });

  const [deletingId, setDeletingId] = useState<number | null>(null);

  /* ---- fetch ---- */
  const fetchEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listPlotEvents(docId, { limit: 500 });
      setEvents(res.items);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [docId]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  /* ---- filtered + sorted ---- */
  const filtered = useMemo(() => {
    let list = events;
    if (chapterFilter !== "all") {
      list = list.filter((e) => e.chapter_index === chapterFilter);
    }
    return [...list].sort((a, b) => {
      if (a.chapter_index == null && b.chapter_index == null) return 0;
      if (a.chapter_index == null) return 1;
      if (b.chapter_index == null) return -1;
      return a.chapter_index - b.chapter_index;
    });
  }, [events, chapterFilter]);

  /* ---- helpers ---- */
  const chapterLabel = (idx: number | null) =>
    idx == null ? "未关联" : `第${idx}章`;

  const findChapterIdByIndex = (idx: number): number | undefined =>
    chapters.find((c) => c.chapter_index === idx)?.id;

  /* ---- create ---- */
  const handleCreate = async () => {
    if (!createForm.summary.trim()) return;
    try {
      await createPlotEvent(docId, toPayload(createForm));
      setShowCreate(false);
      setCreateForm({ ...EMPTY_FORM });
      await fetchEvents();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "创建失败");
    }
  };

  /* ---- edit ---- */
  const startEdit = (ev: PlotEventListItem) => {
    // We need the full read to get involved_character_ids; use event data from list + re-fetch
    setEditId(ev.id);
    setEditForm({
      chapter_index:
        ev.chapter_index == null ? "" : String(ev.chapter_index),
      event_type: ev.event_type,
      summary: ev.summary,
      involved_character_ids: "", // will be filled if we have it from expanded
    });
  };

  const startEditFromRead = (ev: PlotEventRead) => {
    setEditId(ev.id);
    setEditForm({
      chapter_index:
        ev.chapter_index == null ? "" : String(ev.chapter_index),
      event_type: ev.event_type ?? PLOT_EVENT_TYPE_OPTIONS[0],
      summary: ev.summary,
      involved_character_ids:
        ev.involved_character_ids?.join(", ") ?? "",
    });
  };

  const handleUpdate = async () => {
    if (editId == null || !editForm.summary.trim()) return;
    try {
      await updatePlotEvent(docId, editId, toPayload(editForm));
      setEditId(null);
      setEditForm({ ...EMPTY_FORM });
      await fetchEvents();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "更新失败");
    }
  };

  /* ---- delete ---- */
  const handleDelete = async (id: number) => {
    try {
      await deletePlotEvent(docId, id);
      setDeletingId(null);
      if (expandedId === id) {
        setExpandedId(null);
        setExpandedDetail(null);
      }
      await fetchEvents();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  };

  /* ---- chapter options for selects ---- */
  const chapterOptions = useMemo(
    () =>
      [...chapters]
        .sort((a, b) => a.chapter_index - b.chapter_index)
        .map((c) => ({
          value: String(c.chapter_index),
          label: `第${c.chapter_index}章: ${c.title}`,
        })),
    [chapters],
  );

  /* ================================================================ */
  /*  Render                                                           */
  /* ================================================================ */

  return (
    <div
      style={{
        width: 200,
        background: "var(--surface)",
        borderLeft: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {/* ---- header ---- */}
      <div
        style={{
          padding: "8px 8px 4px",
          borderBottom: "1px solid var(--border-hairline)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <h3
          style={{
            margin: 0,
            fontSize: 13,
            fontWeight: 600,
            color: "var(--fg)",
          }}
        >
          📋 剧情事件
        </h3>
        <button
          onClick={() => {
            setShowCreate((v) => !v);
            setCreateForm({ ...EMPTY_FORM });
          }}
          style={{
            fontSize: 11,
            padding: "2px 6px",
            borderRadius: 4,
            border: "1px solid var(--border-subtle)",
            background: "var(--accent)",
            color: "#fff",
            cursor: "pointer",
          }}
        >
          + 添加
        </button>
      </div>

      {/* ---- chapter filter ---- */}
      <div style={{ padding: "4px 8px" }}>
        <select
          value={chapterFilter === "all" ? "all" : String(chapterFilter)}
          onChange={(e) =>
            setChapterFilter(
              e.target.value === "all" ? "all" : Number(e.target.value),
            )
          }
          style={{
            width: "100%",
            fontSize: 11,
            padding: "2px 4px",
            borderRadius: 4,
            border: "1px solid var(--border-subtle)",
            background: "var(--bg)",
            color: "var(--fg)",
          }}
        >
          <option value="all">全部章节</option>
          {chapters.map((c) => (
            <option key={c.id} value={String(c.chapter_index)}>
              第{c.chapter_index}章: {c.title}
            </option>
          ))}
        </select>
      </div>

      {/* ---- create form ---- */}
      {showCreate && (
        <div
          style={{
            padding: "6px 8px",
            borderBottom: "1px solid var(--border-hairline)",
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <select
            value={createForm.chapter_index}
            onChange={(e) =>
              setCreateForm((f) => ({ ...f, chapter_index: e.target.value }))
            }
            style={{
              fontSize: 11,
              padding: "2px 4px",
              borderRadius: 4,
              border: "1px solid var(--border-subtle)",
              background: "var(--bg)",
              color: "var(--fg)",
            }}
          >
            <option value="">未关联</option>
            {chapterOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>

          <select
            value={createForm.event_type}
            onChange={(e) =>
              setCreateForm((f) => ({ ...f, event_type: e.target.value }))
            }
            style={{
              fontSize: 11,
              padding: "2px 4px",
              borderRadius: 4,
              border: "1px solid var(--border-subtle)",
              background: "var(--bg)",
              color: "var(--fg)",
            }}
          >
            {PLOT_EVENT_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>

          <textarea
            placeholder="剧情摘要 *"
            rows={3}
            value={createForm.summary}
            onChange={(e) =>
              setCreateForm((f) => ({ ...f, summary: e.target.value }))
            }
            style={{
              fontSize: 11,
              padding: "2px 4px",
              borderRadius: 4,
              border: "1px solid var(--border-subtle)",
              background: "var(--bg)",
              color: "var(--fg)",
              resize: "vertical",
            }}
          />

          <input
            placeholder="涉及角色ID (逗号分隔)"
            value={createForm.involved_character_ids}
            onChange={(e) =>
              setCreateForm((f) => ({
                ...f,
                involved_character_ids: e.target.value,
              }))
            }
            style={{
              fontSize: 11,
              padding: "2px 4px",
              borderRadius: 4,
              border: "1px solid var(--border-subtle)",
              background: "var(--bg)",
              color: "var(--fg)",
            }}
          />

          <div style={{ display: "flex", gap: 4 }}>
            <button
              onClick={handleCreate}
              disabled={!createForm.summary.trim()}
              style={{
                flex: 1,
                fontSize: 11,
                padding: "3px 0",
                borderRadius: 4,
                border: "none",
                background: "var(--accent)",
                color: "#fff",
                cursor: "pointer",
                opacity: createForm.summary.trim() ? 1 : 0.5,
              }}
            >
              保存
            </button>
            <button
              onClick={() => {
                setShowCreate(false);
                setCreateForm({ ...EMPTY_FORM });
              }}
              style={{
                flex: 1,
                fontSize: 11,
                padding: "3px 0",
                borderRadius: 4,
                border: "1px solid var(--border-subtle)",
                background: "var(--surface-2)",
                color: "var(--fg-secondary)",
                cursor: "pointer",
              }}
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* ---- body ---- */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {/* loading */}
        {loading && (
          <div
            style={{
              padding: 16,
              textAlign: "center",
              fontSize: 11,
              color: "var(--muted)",
            }}
          >
            加载中...
          </div>
        )}

        {/* error */}
        {error && (
          <div
            style={{
              padding: 8,
              fontSize: 11,
              color: "var(--danger)",
              textAlign: "center",
            }}
          >
            {error}
          </div>
        )}

        {/* empty */}
        {!loading && !error && filtered.length === 0 && (
          <div
            style={{
              padding: 16,
              textAlign: "center",
              fontSize: 11,
              color: "var(--muted)",
            }}
          >
            暂无剧情事件
          </div>
        )}

        {/* list */}
        {!loading &&
          filtered.map((ev) => {
            const isExpanded = expandedId === ev.id;
            const isEditing = editId === ev.id;
            const isDeleting = deletingId === ev.id;

            return (
              <div
                key={ev.id}
                style={{
                  padding: "6px 8px",
                  borderBottom: "1px solid var(--border-hairline)",
                  cursor: "pointer",
                  background: isExpanded
                    ? "var(--surface-2)"
                    : "transparent",
                }}
                onClick={() => {
                  if (isEditing || isDeleting) return;
                  if (isExpanded) {
                    setExpandedId(null);
                    setExpandedDetail(null);
                  } else {
                    setExpandedId(ev.id);
                    setExpandedLoading(true);
                    getPlotEvent(docId, ev.id)
                      .then((detail) => setExpandedDetail(detail))
                      .catch(() => setExpandedDetail(null))
                      .finally(() => setExpandedLoading(false));
                  }
                }}
              >
                {/* row 1 */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    marginBottom: 2,
                  }}
                >
                  <span
                    style={{
                      fontSize: 9,
                      color: "var(--muted)",
                    }}
                  >
                    {chapterLabel(ev.chapter_index)}
                  </span>
                  <span
                    style={{
                      fontSize: 9,
                      padding: "0 4px",
                      borderRadius: 3,
                      background: "var(--surface-2)",
                      color: "var(--fg-secondary)",
                    }}
                  >
                    {ev.event_type}
                  </span>
                </div>

                {/* row 2 — summary */}
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--fg)",
                    display: "-webkit-box",
                    WebkitLineClamp: isExpanded ? undefined : 2,
                    WebkitBoxOrient: "vertical",
                    overflow: isExpanded ? "visible" : "hidden",
                  }}
                >
                  {ev.summary}
                </div>

                {/* expanded details */}
                {isExpanded && !isEditing && !isDeleting && (
                  <div
                    style={{ marginTop: 4 }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {expandedLoading ? (
                      <div
                        style={{
                          fontSize: 10,
                          color: "var(--muted)",
                          marginBottom: 4,
                        }}
                      >
                        加载详情...
                      </div>
                    ) : (
                      expandedDetail &&
                      expandedDetail.involved_character_ids &&
                      expandedDetail.involved_character_ids.length > 0 && (
                        <div
                          style={{
                            fontSize: 10,
                            color: "var(--muted)",
                            marginBottom: 4,
                          }}
                        >
                          涉及角色:{" "}
                          {expandedDetail.involved_character_ids
                            .map((id) => `#${id}`)
                            .join(", ")}
                        </div>
                      )
                    )}

                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {/* jump to chapter */}
                      {onSelectChapter &&
                        ev.chapter_index != null &&
                        (() => {
                          const chId = findChapterIdByIndex(ev.chapter_index);
                          if (chId == null) return null;
                          return (
                            <button
                              onClick={() => onSelectChapter(chId)}
                              style={{
                                fontSize: 10,
                                padding: "1px 6px",
                                borderRadius: 3,
                                border: "none",
                                background: "transparent",
                                color: "var(--accent)",
                                cursor: "pointer",
                              }}
                            >
                              → 跳转
                            </button>
                          );
                        })()}

                      <button
                        onClick={() =>
                          expandedDetail
                            ? startEditFromRead(expandedDetail)
                            : startEdit(ev)
                        }
                        style={{
                          fontSize: 10,
                          padding: "1px 6px",
                          borderRadius: 3,
                          border: "1px solid var(--border-subtle)",
                          background: "var(--surface)",
                          color: "var(--fg-secondary)",
                          cursor: "pointer",
                        }}
                      >
                        编辑
                      </button>
                      <button
                        onClick={() => setDeletingId(ev.id)}
                        style={{
                          fontSize: 10,
                          padding: "1px 6px",
                          borderRadius: 3,
                          border: "1px solid var(--border-subtle)",
                          background: "var(--surface)",
                          color: "var(--danger)",
                          cursor: "pointer",
                        }}
                      >
                        删除
                      </button>
                    </div>
                  </div>
                )}

                {/* delete confirmation */}
                {isDeleting && (
                  <div
                    style={{ marginTop: 4 }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div
                      style={{
                        fontSize: 11,
                        color: "var(--danger)",
                        marginBottom: 4,
                      }}
                    >
                      确认删除？
                    </div>
                    <div style={{ display: "flex", gap: 4 }}>
                      <button
                        onClick={() => handleDelete(ev.id)}
                        style={{
                          fontSize: 10,
                          padding: "1px 6px",
                          borderRadius: 3,
                          border: "none",
                          background: "var(--danger)",
                          color: "#fff",
                          cursor: "pointer",
                        }}
                      >
                        确认
                      </button>
                      <button
                        onClick={() => setDeletingId(null)}
                        style={{
                          fontSize: 10,
                          padding: "1px 6px",
                          borderRadius: 3,
                          border: "1px solid var(--border-subtle)",
                          background: "var(--surface)",
                          color: "var(--fg-secondary)",
                          cursor: "pointer",
                        }}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                )}

                {/* edit form (inline) */}
                {isEditing && (
                  <div
                    style={{
                      marginTop: 4,
                      display: "flex",
                      flexDirection: "column",
                      gap: 4,
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <select
                      value={editForm.chapter_index}
                      onChange={(e) =>
                        setEditForm((f) => ({
                          ...f,
                          chapter_index: e.target.value,
                        }))
                      }
                      style={{
                        fontSize: 11,
                        padding: "2px 4px",
                        borderRadius: 4,
                        border: "1px solid var(--border-subtle)",
                        background: "var(--bg)",
                        color: "var(--fg)",
                      }}
                    >
                      <option value="">未关联</option>
                      {chapterOptions.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>

                    <select
                      value={editForm.event_type}
                      onChange={(e) =>
                        setEditForm((f) => ({
                          ...f,
                          event_type: e.target.value,
                        }))
                      }
                      style={{
                        fontSize: 11,
                        padding: "2px 4px",
                        borderRadius: 4,
                        border: "1px solid var(--border-subtle)",
                        background: "var(--bg)",
                        color: "var(--fg)",
                      }}
                    >
                      {PLOT_EVENT_TYPE_OPTIONS.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>

                    <textarea
                      rows={3}
                      value={editForm.summary}
                      onChange={(e) =>
                        setEditForm((f) => ({
                          ...f,
                          summary: e.target.value,
                        }))
                      }
                      style={{
                        fontSize: 11,
                        padding: "2px 4px",
                        borderRadius: 4,
                        border: "1px solid var(--border-subtle)",
                        background: "var(--bg)",
                        color: "var(--fg)",
                        resize: "vertical",
                      }}
                    />

                    <input
                      placeholder="涉及角色ID (逗号分隔)"
                      value={editForm.involved_character_ids}
                      onChange={(e) =>
                        setEditForm((f) => ({
                          ...f,
                          involved_character_ids: e.target.value,
                        }))
                      }
                      style={{
                        fontSize: 11,
                        padding: "2px 4px",
                        borderRadius: 4,
                        border: "1px solid var(--border-subtle)",
                        background: "var(--bg)",
                        color: "var(--fg)",
                      }}
                    />

                    <div style={{ display: "flex", gap: 4 }}>
                      <button
                        onClick={handleUpdate}
                        disabled={!editForm.summary.trim()}
                        style={{
                          flex: 1,
                          fontSize: 11,
                          padding: "3px 0",
                          borderRadius: 4,
                          border: "none",
                          background: "var(--accent)",
                          color: "#fff",
                          cursor: "pointer",
                          opacity: editForm.summary.trim() ? 1 : 0.5,
                        }}
                      >
                        保存
                      </button>
                      <button
                        onClick={() => {
                          setEditId(null);
                          setEditForm({ ...EMPTY_FORM });
                        }}
                        style={{
                          flex: 1,
                          fontSize: 11,
                          padding: "3px 0",
                          borderRadius: 4,
                          border: "1px solid var(--border-subtle)",
                          background: "var(--surface-2)",
                          color: "var(--fg-secondary)",
                          cursor: "pointer",
                        }}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
      </div>
    </div>
  );
}
