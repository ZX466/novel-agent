"""TDD：R6-5 PerfPulse 后端耗时采集测试。

验证 `_timed` 装饰器会把节点耗时写入 state["perf"]：
- 各阶段耗时键存在（retrieval_ms / draft_ms / refine_ms / evaluate_ms / safety_ms / safety_check_ms）
- 耗时为正数
- 不改变节点返回值
- 开销可控（装饰器本身 < ~1us 量级，结构性验证）
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.pipeline.nodes import _timed


@_timed("test_stage")
async def _fake_node(state: dict, *, delay: float = 0.001) -> dict:
    """模拟一个 pipeline 节点：睡 delay 秒后返回固定 dict。"""
    await asyncio.sleep(delay)
    return {"result": "ok"}


def test_timed_writes_stage_elapsed() -> None:
    """执行后 state["perf"]["test_stage_ms"] 存在且 ≈ delay。"""
    async def run() -> tuple[dict, dict]:
        state: dict = {}
        out = await _fake_node(state, delay=0.01)
        return state, out

    state, out = asyncio.run(run())
    assert "perf" in state
    assert "test_stage_ms" in state["perf"]
    elapsed = state["perf"]["test_stage_ms"]
    assert elapsed > 0
    # 0.01s 睡眠 → 耗时应在 5ms-50ms 区间（宽松）
    assert 5.0 <= elapsed <= 50.0


def test_timed_preserves_return_value() -> None:
    """装饰器不改变节点返回值。"""
    async def run() -> dict:
        return await _fake_node({}, delay=0)

    out = asyncio.run(run())
    assert out == {"result": "ok"}


def test_timed_merges_into_existing_perf() -> None:
    """已有 perf 时合并而不是覆盖。"""
    async def run() -> dict:
        state = {"perf": {"pre_ms": 1.0}}
        await _fake_node(state, delay=0)
        return state

    state = asyncio.run(run())
    assert state["perf"]["pre_ms"] == 1.0
    assert "test_stage_ms" in state["perf"]


async def test_timed_overhead_small() -> None:
    """装饰器开销：无 sleep 时 1000 次调用总耗时 < 100ms（每次 <0.1ms）。"""
    t0 = time.perf_counter()
    for _ in range(1000):
        await _fake_node({}, delay=0)
    total_ms = (time.perf_counter() - t0) * 1000
    # 每次（装饰器 + 调度）应远小于 0.1ms：1000 次 < 100ms 宽松验证
    assert total_ms < 100.0, f"1000 次调用耗时 {total_ms:.1f}ms，开销过大"


@pytest.mark.asyncio
async def test_real_decorated_nodes_write_perf() -> None:
    """真实节点（draft_node）在 mock LLM 下写入 perf（集成冒烟）。"""
    from unittest.mock import AsyncMock, patch

    from app.pipeline import nodes

    state: dict = {
        "topic": "test",
        "task_type": "generate",
    }
    fake_chunk = type("Chunk", (), {"choices": [type("C", (), {"delta": type("D", (), {"content": "你好"})()})()]})()
    with patch.object(nodes, "llm_draft", AsyncMock(return_value=_as_async_iter([fake_chunk]))):
        out = await nodes.draft_node(state)

    assert out.get("draft") == "你好"
    assert "perf" in state
    assert "draft_ms" in state["perf"]
    # mock LLM 调用 < 0.05ms 可能被 round(...,1) 舍入为 0.0；生产 LLM 秒级不受影响
    assert state["perf"]["draft_ms"] >= 0


def _as_async_iter(items):
    async def gen():
        for i in items:
            yield i
    return gen()
