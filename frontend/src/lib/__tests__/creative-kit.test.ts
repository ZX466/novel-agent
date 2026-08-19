import { describe, expect, it } from "vitest";

import { EMPTY_KIT, parseCreativeKit } from "@/lib/creative-kit";

const SAMPLE = {
  world_settings: [
    { title: "修仙界地理", category: "地理", content_text: "九州大陆，灵气浓郁。" },
  ],
  characters: [
    { name: "张三", role: "主角", description: "青云宗弟子", arc_summary: "入宗修炼" },
  ],
  outline: "第一章：张三入宗。第二章：突破练气。",
};

describe("parseCreativeKit", () => {
  it("parses a plain JSON object", () => {
    const kit = parseCreativeKit(JSON.stringify(SAMPLE));
    expect(kit.world_settings).toHaveLength(1);
    expect(kit.world_settings[0].title).toBe("修仙界地理");
    expect(kit.characters).toHaveLength(1);
    expect(kit.characters[0].name).toBe("张三");
    expect(kit.characters[0].role).toBe("主角");
    expect(kit.outline).toContain("第一章");
  });

  it("parses a fenced json block", () => {
    const text = `好的，这是设定包：\n\`\`\`json\n${JSON.stringify(SAMPLE)}\n\`\`\`\n希望对你有帮助。`;
    const kit = parseCreativeKit(text);
    expect(kit.characters).toHaveLength(1);
    expect(kit.characters[0].name).toBe("张三");
  });

  it("parses the first {...} region inside prose", () => {
    const text = `开始生成${JSON.stringify(SAMPLE)}结束`;
    const kit = parseCreativeKit(text);
    expect(kit.world_settings).toHaveLength(1);
    expect(kit.outline).toContain("第一章");
  });

  it("drops entries without a required key", () => {
    const text = JSON.stringify({
      world_settings: [{ content_text: "缺标题" }],
      characters: [{ role: "缺名字" }],
      outline: "",
    });
    const kit = parseCreativeKit(text);
    expect(kit.world_settings).toHaveLength(0);
    expect(kit.characters).toHaveLength(0);
  });

  it("returns EMPTY_KIT for empty or invalid input", () => {
    expect(parseCreativeKit("")).toEqual(EMPTY_KIT);
    expect(parseCreativeKit("not json at all")).toEqual(EMPTY_KIT);
    expect(parseCreativeKit("{broken json")).toEqual(EMPTY_KIT);
  });

  it("is resilient to streamed trailing prose", () => {
    const kit = parseCreativeKit(JSON.stringify(SAMPLE) + "\n（设定已生成完毕）");
    expect(kit.characters).toHaveLength(1);
  });

  it("handles nested braces inside the JSON (brace-depth aware)", () => {
    const withBraces = {
      world_settings: [
        { title: "力量体系", content_text: "境界：{练气}{筑基}{金丹}" },
      ],
      characters: [{ name: "李四", description: "话痨：{哈哈}" }],
      outline: "大纲：{第一幕}",
    };
    const text = `输出如下：${JSON.stringify(withBraces)} 完毕`;
    const kit = parseCreativeKit(text);
    expect(kit.world_settings).toHaveLength(1);
    expect(kit.world_settings[0].content_text).toContain("{练气}{筑基}");
    expect(kit.characters).toHaveLength(1);
    expect(kit.characters[0].name).toBe("李四");
    expect(kit.outline).toContain("{第一幕}");
  });

  it("skips prose braces before the JSON object", () => {
    const text = `注意：{这不是JSON} 然后是 ${JSON.stringify(SAMPLE)}`;
    const kit = parseCreativeKit(text);
    expect(kit.world_settings).toHaveLength(1);
    expect(kit.characters[0].name).toBe("张三");
  });
});
