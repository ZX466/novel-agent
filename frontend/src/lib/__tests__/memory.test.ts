import { describe, expect, it, vi, beforeEach } from "vitest";

/**
 * fetchAllMemoryRows aggregates six kinds into uniform rows for the memory
 * library page. One kind failing must degrade to empty rows for that kind,
 * never break the page load.
 */

const rowsFixture = {
  chapters: {
    items: [
      { id: 1, title: "第一章", chapter_index: 0, content_text: "正文内容", updated_at: "2026-09-13T00:00:00Z" },
    ],
  },
  characters: {
    items: [
      { id: 2, name: "夜烬", role: "主角", description: "少年", arc_summary: "", updated_at: "2026-09-13T00:00:00Z" },
    ],
  },
  worlds: {
    items: [
      { id: 3, title: "火种设定", category: "力量体系", content_text: "铜币引火", updated_at: "2026-09-13T00:00:00Z" },
    ],
  },
  events: {
    items: [
      { id: 4, summary: "夜烬进入火种试炼", event_type: "起", chapter_index: 2, updated_at: "2026-09-13T00:00:00Z" },
    ],
  },
  graph: {
    nodes: [
      { id: 2, name: "夜烬" },
      { id: 9, name: "灰姑" },
    ],
    edges: [
      { id: 10, subject_id: 2, object_id: 9, relation_type: "救助", strength: 0.8 },
    ],
  },
  knowledge: {
    items: [
      { title: "设定集.txt", chunk_count: 5, created_at: "2026-09-13T00:00:00Z" },
    ],
  },
};

function mockLibs(overrides: Partial<Record<string, unknown>> = {}) {
  vi.resetModules();
  vi.doMock("../chapters", () => ({
    listChapters: (overrides.listChapters as never) ?? vi.fn(async () => rowsFixture.chapters),
  }));
  vi.doMock("../characters", () => ({
    listCharacters: (overrides.listCharacters as never) ?? vi.fn(async () => rowsFixture.characters),
  }));
  vi.doMock("../world-settings", () => ({
    listWorldSettings: (overrides.listWorldSettings as never) ?? vi.fn(async () => rowsFixture.worlds),
  }));
  vi.doMock("../plot-events", () => ({
    listPlotEvents: (overrides.listPlotEvents as never) ?? vi.fn(async () => rowsFixture.events),
  }));
  vi.doMock("../character-relationships", () => ({
    fetchRelationshipGraph: (overrides.fetchRelationshipGraph as never) ?? vi.fn(async () => rowsFixture.graph),
  }));
}

describe("fetchAllMemoryRows", () => {
  beforeEach(() => {
    vi.resetModules();
    // config/settings imports touch window/localStorage at module scope in
    // some paths; provide jsdom-safe stubs.
    vi.doMock("../config", () => ({ backendUrl: "http://test.local" }));
    vi.doMock("../settings", () => ({
      embeddingProviderHeaders: () => ({}),
      ownerAuthHeaders: () => ({}),
    }));
    mockLibs();
    // knowledge lib uses fetch — stub a 200 with our fixture.
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => rowsFixture.knowledge,
    } as unknown as Response)));
  });

  it("aggregates all six kinds into rows with labels/badges", async () => {
    const { fetchAllMemoryRows } = await import("../memory");
    const rows = await fetchAllMemoryRows(1);
    const kinds = rows.map((r) => r.kind);
    expect(kinds).toContain("chapter");
    expect(kinds).toContain("character");
    expect(kinds).toContain("world");
    expect(kinds).toContain("event");
    expect(kinds).toContain("relationship");
    expect(kinds).toContain("knowledge");
    expect(rows).toHaveLength(6);
    const rel = rows.find((r) => r.kind === "relationship")!;
    expect(rel.title).toContain("夜烬");
    expect(rel.title).toContain("灰姑");
    expect(rel.title).toContain("救助");
    const ev = rows.find((r) => r.kind === "event")!;
    // 09-15: badge 现为 1 起始(index 2 → 第3章,与章节标题「第N章」一致)。
    expect(ev.badge).toContain("第3章");
  });

  it("degrades a failing kind to zero rows instead of rejecting", async () => {
    mockLibs({
      listPlotEvents: vi.fn(async () => {
        throw new Error("boom");
      }),
      fetchRelationshipGraph: vi.fn(async () => {
        throw new Error("boom");
      }),
    });
    const { fetchAllMemoryRows } = await import("../memory");
    const rows = await fetchAllMemoryRows(1);
    expect(rows.map((r) => r.kind)).not.toContain("event");
    expect(rows.map((r) => r.kind)).not.toContain("relationship");
    expect(rows.map((r) => r.kind)).toContain("chapter"); // others intact
  });
});
