import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { RelationshipGraph } from "../RelationshipGraph";
import * as api from "@/lib/character-relationships";

vi.mock("@/lib/character-relationships", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/character-relationships")>();
  return {
    ...actual,
    fetchRelationshipGraph: vi.fn(),
    upsertRelationship: vi.fn(),
    deleteRelationship: vi.fn(),
    importRelationships: vi.fn(),
  };
});

const mockedFetch = vi.mocked(api.fetchRelationshipGraph);

const GRAPH = {
  nodes: [
    { id: 1, name: "林动", role: "主角" },
    { id: 2, name: "应欢欢", role: "配角" },
  ],
  edges: [
    {
      subject_id: 1,
      object_id: 2,
      relation_type: "道侣",
      description: "",
      strength: 7,
    },
  ],
};

describe("RelationshipGraph", () => {
  beforeEach(() => {
    mockedFetch.mockResolvedValue(GRAPH);
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders nodes and edges from the API", async () => {
    render(<RelationshipGraph docId={1} />);
    await waitFor(() => {
      expect(screen.getByText(/2 人 \/ 1 条关系/)).toBeTruthy();
    });
    // node name appears twice (initials inside circle + label below) — use getAllBy
    expect(screen.getAllByText("林动").length).toBeGreaterThan(0);
    expect(screen.getAllByText("应欢欢").length).toBeGreaterThan(0);
  });

  it("shows empty hint when no characters exist", async () => {
    mockedFetch.mockResolvedValue({ nodes: [], edges: [] });
    render(<RelationshipGraph docId={1} />);
    await waitFor(() => {
      expect(screen.getByText(/还没有人物/)).toBeTruthy();
    });
  });

  it("shows API error message verbatim on failure", async () => {
    mockedFetch.mockRejectedValue(new Error("请求失败 (401)"));
    render(<RelationshipGraph docId={1} />);
    await waitFor(() => {
      expect(screen.getByText("请求失败 (401)")).toBeTruthy();
    });
  });

  it("edge click opens detail with strength buttons; PUT failure shows server text", async () => {
    vi.mocked(api.upsertRelationship).mockRejectedValue(
      new Error("关系已存在"),
    );
    render(<RelationshipGraph docId={1} />);
    await waitFor(() => screen.getByText(/2 人 \/ 1 条关系/));
    // click the edge label (relation text sits mid-edge)
    fireEvent.click(screen.getByText("道侣"));
    await waitFor(() => screen.getByText("删除"));
    fireEvent.click(screen.getByText("7"));
    await waitFor(() => {
      expect(screen.getByText("关系已存在")).toBeTruthy();
    });
  });

  it("manual import adds a draft item and calls importRelationships", async () => {
    vi.mocked(api.importRelationships).mockResolvedValue({
      created: 1,
      updated: 0,
      skipped: 0,
    });
    render(<RelationshipGraph docId={1} />);
    await waitFor(() => screen.getByText(/2 人 \/ 1 条关系/));
    fireEvent.click(screen.getByText(/按名字添加关系/));
    const inputs = screen.getAllByRole("textbox") as HTMLInputElement[];
    fireEvent.change(inputs[0], { target: { value: "林动" } });
    fireEvent.change(inputs[1], { target: { value: "师徒" } });
    fireEvent.change(inputs[2], { target: { value: "应欢欢" } });
    fireEvent.click(screen.getByText("添加"));
    await waitFor(() => screen.getByText(/导入 1 条/));
    fireEvent.click(screen.getByText(/导入 1 条/));
    await waitFor(() => {
      expect(api.importRelationships).toHaveBeenCalledWith(1, [
        { subject_name: "林动", object_name: "应欢欢", relation_type: "师徒" },
      ]);
    });
  });
});
