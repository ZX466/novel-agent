import { describe, expect, it } from "vitest";
import { formsCycle } from "../plot-events";

/**
 * R10-⑧ 前驱下拉的客户端环路预检: 在创建/编辑表单里为 `editedId` 选择
 * 前驱 `chosenPrevId` 时,沿 chosenPrevId 的 prev_event_id 链走,若能回到
 * editedId 则该选择会成环——面板禁用该选项。服务端不硬拒环（R6-2 警告
 * 式设计,时间线出 cycle warning）,这里是体验层拦截。
 *
 * `events` 是"选完之后"的全集快照——调用方把本次选择并入副本再传入,
 * 本函数只读不写。
 */

describe("formsCycle", () => {
  const chain = [
    { id: 1, prev_event_id: null },
    { id: 2, prev_event_id: 1 },
    { id: 3, prev_event_id: 2 },
    { id: 4, prev_event_id: 3 }, // stored: 4←3←2←1
  ];

  it("detects pointing the chain head back at its tail", () => {
    // event 1 (head) choosing prev=4 (tail) closes 1→4→3→2→1
    expect(formsCycle(1, 4, chain)).toBe(true);
  });

  it("allows a normal predecessor from the chain", () => {
    // 4.prev=1: walking 1→null never returns to 4
    expect(formsCycle(4, 1, chain)).toBe(false);
    expect(formsCycle(4, 3, chain)).toBe(false);
  });

  it("rejects self-reference immediately", () => {
    expect(formsCycle(2, 2, chain)).toBe(true);
  });

  it("handles dangling/foreign prev links without looping forever", () => {
    const broken = [
      { id: 1, prev_event_id: 999 }, // dangling
      { id: 2, prev_event_id: 1 },
      { id: 3, prev_event_id: 2 },
    ];
    // walk from 3: 3→2→1→999 (not in set) → stop, never hits 1's editor? No:
    // editing 1 with prev=3 walks 3→2→1 — hits edited id → cycle.
    expect(formsCycle(1, 3, broken)).toBe(true);
    // prev not in the set at all → chain dead-ends immediately
    expect(formsCycle(2, 999, broken)).toBe(false);
  });

  it("is false for the first event or an unrelated snapshot", () => {
    expect(formsCycle(1, 2, [])).toBe(false);
  });

  it("two-node cycle: head points at tail that already points back", () => {
    const pair = [
      { id: 7, prev_event_id: 8 },
      { id: 8, prev_event_id: null },
    ];
    // editing 8 to choose prev=7: walk 7→8 = edited id → cycle
    expect(formsCycle(8, 7, pair)).toBe(true);
    // editing 8 to keep a fresh tail: no cycle
    expect(formsCycle(8, null, pair)).toBe(false);
  });
});
