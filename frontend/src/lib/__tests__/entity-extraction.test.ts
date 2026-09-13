import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Task 3: 大纲实体提取补人物关系线。
 * extractAndCreateEntities 在三类实体创建完成后，若提取结果带
 * relationships（{subject_name,object_name,relation_type,strength,...}），
 * 必须复用名字解析的批量导入端点 importRelationships；导入失败不得拖垮
 * 整次提取（计数 0）。formatExtractionSummary 仅在 >0 时追加「N 条关系」。
 */
vi.mock("@/lib/extract-entities", () => ({
  extractEntitiesFromOutline: vi.fn(),
}));
vi.mock("@/lib/characters", () => ({ createCharacter: vi.fn() }));
vi.mock("@/lib/world-settings", () => ({ createWorldSetting: vi.fn() }));
vi.mock("@/lib/plot-events", () => ({ createPlotEvent: vi.fn() }));
vi.mock("@/lib/character-relationships", () => ({
  importRelationships: vi.fn(),
}));

import { extractEntitiesFromOutline } from "@/lib/extract-entities";
import { createCharacter } from "@/lib/characters";
import { createWorldSetting } from "@/lib/world-settings";
import { createPlotEvent } from "@/lib/plot-events";
import { importRelationships } from "@/lib/character-relationships";
import {
  extractAndCreateEntities,
  formatExtractionSummary,
  type ExtractionOutcome,
} from "../entity-extraction";

const mockedExtract = vi.mocked(extractEntitiesFromOutline);
const mockedImport = vi.mocked(importRelationships);

function baseEntities() {
  return {
    characters: [{ name: "陈默" }],
    world_settings: [],
    plot_events: [],
  };
}

describe("extractAndCreateEntities relationships", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedExtract.mockResolvedValue(baseEntities());
    mockedImport.mockResolvedValue({ created: 1, updated: 0, skipped: 0 });
  });

  it("imports extracted relationships by name and counts them in the outcome", async () => {
    mockedExtract.mockResolvedValue({
      ...baseEntities(),
      relationships: [
        {
          subject_name: "陈默",
          object_name: "苏晚晴",
          relation_type: "搭档",
          strength: 8,
        },
      ],
    });

    const outcome = await extractAndCreateEntities(1, "大纲");

    expect(mockedImport).toHaveBeenCalledTimes(1);
    expect(mockedImport).toHaveBeenCalledWith(1, [
      { subject_name: "陈默", object_name: "苏晚晴", relation_type: "搭档", strength: 8 },
    ]);
    expect(outcome.relationships).toBe(1);
  });

  it("falls back to the generic relation label and drops absent description", async () => {
    mockedExtract.mockResolvedValue({
      ...baseEntities(),
      relationships: [
        { subject_name: "陈默", object_name: "苏晚晴", description: "旧识" },
      ],
    });

    await extractAndCreateEntities(1, "大纲");

    expect(mockedImport).toHaveBeenCalledWith(1, [
      {
        subject_name: "陈默",
        object_name: "苏晚晴",
        relation_type: "关系",
        description: "旧识",
        strength: undefined,
      },
    ]);
  });

  it("does not call importRelationships when extraction has no relationships", async () => {
    const outcome = await extractAndCreateEntities(1, "大纲");

    expect(mockedImport).not.toHaveBeenCalled();
    expect(outcome.relationships).toBe(0);
  });

  it("relationship import failure must not fail the extraction (count 0)", async () => {
    mockedExtract.mockResolvedValue({
      ...baseEntities(),
      relationships: [{ subject_name: "A", object_name: "B", relation_type: "敌对" }],
    });
    mockedImport.mockRejectedValue(new Error("network down"));

    const outcome = await extractAndCreateEntities(1, "大纲");

    expect(outcome.characters).toBe(1);
    expect(outcome.relationships).toBe(0);
  });
});

describe("formatExtractionSummary relationships", () => {
  function outcome(relationships = 0, extra: Partial<ExtractionOutcome> = {}): ExtractionOutcome {
    return {
      characters: 0,
      worldSettings: 0,
      plotEvents: 0,
      failed: 0,
      duplicates: 0,
      relationships,
      ...extra,
    };
  }

  it("appends the relationship count only when > 0", () => {
    expect(formatExtractionSummary(outcome(1))).toContain("1 条关系");
    expect(formatExtractionSummary(outcome(2))).toContain("2 条关系");
  });

  it("omits the relationship segment when count is 0 or absent", () => {
    expect(formatExtractionSummary(outcome())).not.toContain("关系");
    expect(formatExtractionSummary(outcome(0))).not.toContain("关系");
  });

  it("keeps the duplicate/failure notes alongside the relationship segment", () => {
    const s = formatExtractionSummary(outcome(1, { failed: 1, duplicates: 1 }));
    expect(s).toContain("已存在，已跳过");
    expect(s).toContain("1 条关系");
  });
});
