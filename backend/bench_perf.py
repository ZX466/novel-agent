"""离线性能基准：验证 talking.txt 任务中的性能瓶颈假设。

只测量不依赖网络的模块：
1. embed_text 每次调用新建 AsyncOpenAI client 的开销（_get_client 每次 new）
2. SSE 每 token 编码开销（_sse + json.dumps）
3. asyncio.Queue 无界队列的背压特性说明（结构性）
4. retrieval 串行 vs 并发 的延迟模型（结构性）
"""
import asyncio
import json
import time

# --- 1. embedding client 创建成本 -------------------------------------------
# embedding._get_client 每次调用都新建 AsyncOpenAI（timeout=60 等参数），
# 这是无网络的开销，但对象构建本身有成本。


def bench_client_creation(n: int = 2000) -> float:
    from app.llm.embedding import _get_client

    start = time.perf_counter()
    for _ in range(n):
        # 传 None → 走 .env 分支（settings.embedding_api_key 等）
        _get_client(None)
    return (time.perf_counter() - start) / n


# --- 2. SSE 编码成本 ---------------------------------------------------------
def bench_sse_encode(token: str = "字") -> float:
    from app.api.chat import _sse

    n = 50000
    start = time.perf_counter()
    for _ in range(n):
        _sse({"type": "text-delta", "id": "text-0", "delta": token})
    return (time.perf_counter() - start) / n


def bench_json_dumps(token: str = "字") -> float:
    n = 50000
    start = time.perf_counter()
    for _ in range(n):
        json.dumps({"type": "text-delta", "id": "text-0", "delta": token}, ensure_ascii=False)
    return (time.perf_counter() - start) / n


# --- 3. 串行 vs 并发 RAG 延迟模型（结构性，单元可离线验证） ------------------
# 4 个 pgvector 查询，每个耗时 t_query（网络+DB）。
# 串行: 4 * t_query；并发: t_query（+调度开销）。
def latency_serial(n_queries: int, t_each_ms: float) -> float:
    return n_queries * t_each_ms


def latency_parallel(n_queries: int, t_each_ms: float) -> float:
    return t_each_ms  # asyncio.gather 全部并发


if __name__ == "__main__":
    print("=== 离线性能基准 ===")
    t = bench_client_creation()
    print(f"1. embedding client 创建: {t*1000:.3f} ms/次  (每次 embed_text 都新建)")
    t = bench_sse_encode()
    print(f"2. SSE 编码: {t*1000:.4f} ms/事件  (每 token 一个事件)")
    t = bench_json_dumps()
    print(f"   json.dumps 单独: {t*1000:.4f} ms/次")

    print("\n3. RAG 串行 vs 并发延迟模型（假设单查询 30ms 网络+DB）:")
    for tq in (20, 50, 100):
        s = latency_serial(4, tq)
        p = latency_parallel(4, tq)
        print(f"   单查询 {tq}ms: 串行 {s:.0f}ms | 并发 {p:.0f}ms | 省 {(s-p):.0f}ms")
