/**
 * extractVolumeContext (09-14 优化2): for 卷→章 title-only outlines, dig out
 * the CURRENT volume's summary (the 3-5 sentence paragraph above the volume
 * heading's chapter block... actually below it) and the previous/next
 * chapter titles around the current one, so chapter generation knows its
 * volume even without per-chapter synopses.
 */
import { describe, expect, it } from "vitest";

import { extractVolumeContext } from "@/components/AIToolPanel";

const OUTLINE = [
  "第一卷 长夜初火",
  "陆沉在荒原觉醒低语之力，遭遇猎火者追杀，随铁千山学艺，点燃第一簇火种。",
  "第1章 火种",
  "第2章 永夜将至",
  "第3章 猎火者",
  "第二卷 万灵原之约",
  "陆沉进入万灵原与白夜结伴，发现神族篡改世界之语的真相，卷末白夜沉睡。",
  "第4章 风中的信",
  "第5章 焚语之宴",
  "第6章 罪域之音",
].join("\n");

describe("extractVolumeContext", () => {
  it("finds the volume summary + neighbor titles for a mid-volume chapter", () => {
    const vc = extractVolumeContext(OUTLINE, "第5章 焚语之宴");
    expect(vc).not.toBeNull();
    expect(vc!.volume_summary).toContain("万灵原之约");
    expect(vc!.volume_summary).toContain("白夜");
    expect(vc!.prev_title).toBe("第4章 风中的信");
    expect(vc!.next_title).toBe("第6章 罪域之音");
  });

  it("works for the first chapter of a volume (prev = last chapter of previous volume)", () => {
    const vc = extractVolumeContext(OUTLINE, "第4章 风中的信");
    expect(vc!.prev_title).toBe("第3章 猎火者");
    expect(vc!.next_title).toBe("第5章 焚语之宴");
  });

  it("returns null when the outline has no chapter headings", () => {
    expect(extractVolumeContext("没有章节标题的文本", "第1章 X")).toBeNull();
  });

  it("returns null when the chapter cannot be located (falls back handled by caller)", () => {
    expect(extractVolumeContext(OUTLINE, "第九百章 不存在的章")).toBeNull();
  });
});
