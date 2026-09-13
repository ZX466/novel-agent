import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { WordCountBar } from "../WordCountBar";

/**
 * R10-⑤ 嵌入完成提醒: 章节保存后嵌入在后台进行(几秒),期间 RAG 检索
 * 不含最新文本。`embeddingPending=true` 时显示"索引中"徽标;轮询到清除后
 * 由父级转 false,徽标短暂显示"已索引"再消失(父级控制)。
 */
describe("WordCountBar — embedding indexing indicator", () => {
  it("shows the 索引中 badge when embeddingPending is true", () => {
    render(
      <WordCountBar
        chapterWordCount={100}
        totalWordCount={200}
        saveState="saved"
        dirty={false}
        onSave={() => {}}
        onAutoSave={() => {}}
        embeddingPending={true}
      />,
    );
    expect(screen.getByText("索引中")).toBeTruthy();
  });

  it("shows no badge when embeddingPending is false", () => {
    render(
      <WordCountBar
        chapterWordCount={100}
        totalWordCount={200}
        saveState="saved"
        dirty={false}
        onSave={() => {}}
        onAutoSave={() => {}}
        embeddingPending={false}
      />,
    );
    expect(screen.queryByText("索引中")).toBeNull();
  });
});
