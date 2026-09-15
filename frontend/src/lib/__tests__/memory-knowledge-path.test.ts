import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 09-15 修复:记忆库知识文档 404——前端调
 * `/v1/documents/{id}/knowledge-docs`,后端注册的路由是
 * `/v1/documents/{id}/knowledge`(容器内 OpenAPI 路由遍历确认)。
 * 从 R10-⑥(3c24106)上线起知识文档 tab 恒 404(聚合降级掩盖)。
 * 另:后端 limit 校验 le=200,前端传 500 即使路径对也 422。
 */

vi.mock("../config", () => ({ backendUrl: "http://test.local" }));
vi.mock("../settings", () => ({
  embeddingProviderHeaders: () => ({}),
  ownerAuthHeaders: () => ({}),
}));

const fetchCalls: Array<{ url: string; init?: RequestInit }> = [];

function mockFetch(ok: boolean, status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      fetchCalls.push({ url: String(url), init });
      return {
        ok,
        status,
        json: async () => body,
      } as unknown as Response;
    }),
  );
}

describe("knowledge docs 客户端路径与 limit", () => {
  beforeEach(() => {
    vi.resetModules();
    // stubGlobal 不清掉会泄漏到后跑的测试文件(实测污染 memory.test.ts
    // 的降级用例——那里的 mock fetch 永远 ok,failing kind 不再降级)。
    vi.unstubAllGlobals();
    fetchCalls.length = 0;
  });

  it("listKnowledgeDocs 打到 /knowledge 路由且 limit ≤ 200", async () => {
    mockFetch(true, 200, { items: [], total: 0 });
    const { listKnowledgeDocs } = await import("../memory");
    await listKnowledgeDocs(313);
    expect(fetchCalls).toHaveLength(1);
    const url = fetchCalls[0].url;
    expect(url).toContain("/v1/documents/313/knowledge?");
    expect(url).not.toContain("knowledge-docs");
    const limit = Number(new URL(url).searchParams.get("limit"));
    expect(limit).toBeGreaterThanOrEqual(1);
    expect(limit).toBeLessThanOrEqual(200);
  });

  it("uploadKnowledgeDoc POST 到 /knowledge(非 knowledge-docs)", async () => {
    mockFetch(true, 201, { title: "a.txt", chunk_count: 1 });
    const { uploadKnowledgeDoc } = await import("../memory");
    const file = new File(["hello"], "a.txt", { type: "text/plain" });
    await uploadKnowledgeDoc(1, file);
    expect(fetchCalls[0].url).toContain("/v1/documents/1/knowledge");
    expect(fetchCalls[0].url).not.toContain("knowledge-docs");
    expect(fetchCalls[0].init?.method).toBe("POST");
  });

  it("uploadKnowledgeText POST 到 /knowledge(非 knowledge-docs)", async () => {
    mockFetch(true, 201, { title: "t.txt", chunk_count: 1 });
    const { uploadKnowledgeText } = await import("../memory");
    await uploadKnowledgeText(1, "设定", "火种内容");
    expect(fetchCalls[0].url).toContain("/v1/documents/1/knowledge");
    expect(fetchCalls[0].url).not.toContain("knowledge-docs");
  });

  it("deleteKnowledgeDoc DELETE /knowledge/{title}(非 knowledge-docs)", async () => {
    mockFetch(true, 204, undefined);
    const { deleteKnowledgeDoc } = await import("../memory");
    await deleteKnowledgeDoc(1, "设定集.txt");
    expect(fetchCalls[0].url).toContain("/v1/documents/1/knowledge/");
    expect(fetchCalls[0].url).not.toContain("knowledge-docs");
    expect(fetchCalls[0].init?.method).toBe("DELETE");
  });
});
