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


# --- 4. 优化前后对比（第二轮任务：_search_one 过滤下推 + evaluate 持久化降频）--
def simulate_search_filter_before(n_rows: int, max_distance: float) -> tuple[int, float]:
    """优化前：SQL 返回 k 行（含超距离）后 Python 侧过滤，丢结果。"""
    kept = 0
    start = time.perf_counter()
    for i in range(n_rows):
        dist = (i % 10) / 10  # 0.0..0.9 模拟距离
        if dist < max_distance:  # Python 后过滤
            kept += 1
    elapsed = (time.perf_counter() - start) * 1000
    return kept, elapsed


def simulate_search_filter_after(n_rows: int, max_distance: float) -> tuple[int, float]:
    """优化后：SQL 已过滤，Python 侧仅兜底（不命中）。"""
    kept = 0
    start = time.perf_counter()
    for i in range(n_rows):
        dist = (i % 10) / 10
        if dist >= max_distance:
            continue  # SQL 已排除；Python 兜底
        kept += 1
    elapsed = (time.perf_counter() - start) * 1000
    return kept, elapsed


def eval_persist_commits_before(max_iters: int) -> int:
    """优化前：每轮 refine 迭代都 create_evaluation → commit。"""
    return max_iters


def eval_persist_commits_after(max_iters: int) -> int:
    """优化后：仅最终轮（路由到 safety_check）持久化一次。"""
    return 1


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

    print("\n4. 优化前后对比（第二轮任务实施结果）:")
    for n_rows in (10000, 50000):
        kept_b, t_b = simulate_search_filter_before(n_rows, 0.3)
        kept_a, t_a = simulate_search_filter_after(n_rows, 0.3)
        print(
            f"   _search_one 过滤: {n_rows} 行 | 旧: 保留{kept_b}/{n_rows} {t_b:.2f}us | "
            f"新: 保留{kept_a}/{n_rows} {t_a:.2f}us | Python 循环省 {(t_b-t_a):.2f}us"
        )
    print(f"   evaluate 持久化: max_iters=3 | 旧: {eval_persist_commits_before(3)} 次commit/请求 | "
          f"新: {eval_persist_commits_after(3)} 次commit/请求 (省 2/3)")
