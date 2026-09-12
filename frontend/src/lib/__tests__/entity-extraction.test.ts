import { describe, expect, it } from "vitest";
import { formatExtractionSummary, type ExtractionOutcome } from "../entity-extraction";

describe("formatExtractionSummary", () => {
  it("lists created counts without a skip note when nothing failed", () => {
    const o: ExtractionOutcome = {
      characters: 3, worldSettings: 2, plotEvents: 5, failed: 0, duplicates: 0,
    };
    expect(formatExtractionSummary(o)).toBe(
      "已提取 3 个角色、2 个世界观设定、5 个剧情事件",
    );
  });

  it("reports all failures as duplicates when every rejection was a 409", () => {
    const o: ExtractionOutcome = {
      characters: 1, worldSettings: 0, plotEvents: 0, failed: 2, duplicates: 2,
    };
    const s = formatExtractionSummary(o);
    expect(s).toContain("1 个角色");
    expect(s).toContain("已存在，已跳过");
    expect(s).not.toContain("校验失败");
  });

  it("splits duplicates from validation failures when both occurred", () => {
    const o: ExtractionOutcome = {
      characters: 0, worldSettings: 1, plotEvents: 0, failed: 3, duplicates: 2,
    };
    const s = formatExtractionSummary(o);
    expect(s).toContain("2 条已存在跳过");
    expect(s).toContain("1 条校验失败");
  });
});
