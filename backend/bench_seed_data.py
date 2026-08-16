"""真实 DB 基准种子脚本：向 pgvector 灌入测试数据并运行基准。

用法（本地 Docker PG）:
    python bench_seed_data.py seed    # 灌入 4×N 行随机向量
    python bench_seed_data.py bench   # 跑串行 vs 并发 RAG + HNSW 查询延迟
"""
from __future__ import annotations

import asyncio
import random
import sys
import time

import asyncpg

DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/project11"
EMBEDDING_DIM = 1536
PER_COLLECTION = 1000  # 每集合行数


def _rand_vector(seed: int, rng: random.Random) -> list[float]:
    """生成单位长度的随机向量（模拟 embedding）。"""
    vec = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec] if norm else vec


async def seed(conn: asyncpg.Connection) -> None:
    """先清空再灌入 4 集合 × N 行带 embedding 的测试数据。"""
    for table in ("plot_events", "world_settings", "characters", "chapters"):
        await conn.execute(f"TRUNCATE {table} RESTART IDENTITY CASCADE")
    print("已清空旧数据")

    rng = random.Random(42)

    # chapters / characters / world_settings / plot_events 各 N 行
    for i in range(PER_COLLECTION):
        vec = _rand_vector(i, rng)
        vec_str = str(vec)  # pgvector 接受 '[1.0,2.0,...]' 文本格式
        await conn.execute(
            "INSERT INTO chapters (novel_id, chapter_index, title, content_text, summary, word_count, status, embedding) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            1, i, f"Chapter {i}", f"Content {i}" * 10, f"Summary {i}", 100 + i, "active", vec_str,
        )
        await conn.execute(
            "INSERT INTO characters (novel_id, name, role, description, attributes, arc_summary, embedding) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7)",
            1, f"Character {i}", "protagonist", f"Description {i}" * 5, "{}", f"Arc {i}", vec_str,
        )
        await conn.execute(
            "INSERT INTO world_settings (novel_id, category, title, content_text, embedding) "
            "VALUES ($1,$2,$3,$4,$5)",
            1, "geography", f"World {i}", f"WorldDesc {i}" * 5, vec_str,
        )
        await conn.execute(
            "INSERT INTO plot_events (novel_id, chapter_index, event_type, summary, involved_character_ids, embedding) "
            "VALUES ($1,$2,$3,$4,$5,$6)",
            1, i % 200, "beat", f"Event {i}" * 3, "[]", vec_str,
        )
        if i % 100 == 0:
            print(f"  已灌入 {i}/{PER_COLLECTION}")

    # ANALYZE 让 planner 获得统计信息
    await conn.execute("ANALYZE")
    print(f"数据灌入完成：4 集合 × {PER_COLLECTION} 行 (dim={EMBEDDING_DIM}, HNSW 索引已存在)")


def _query(collection: str) -> str:
    """构造该集合的 vector 查询（cosine，LIMIT k）。"""
    return (
        f"SELECT id, embedding <=> $1 AS dist FROM {collection} "
        f"WHERE embedding IS NOT NULL AND embedding <=> $1 < 1.0 "
        f"ORDER BY embedding <=> $1 LIMIT $2"
    )


async def bench(pool: asyncpg.Pool, n_runs: int = 30) -> None:
    """串行 vs 并发 RAG 基准（用连接池模拟 SQLAlchemy 池化场景）。

    - 串行: 4 集合逐条 await（旧实现）
    - 并发: 4 条查询同时在池的不同连接上发出（新实现）
    """
    rng = random.Random(7)
    qvec = str(_rand_vector(0, rng))
    collections = ("chapters", "characters", "world_settings", "plot_events")
    queries = {c: _query(c) for c in collections}

    async def fetch_one(conn: asyncpg.Connection, q: str) -> None:
        await conn.fetch(q, qvec, 3)

    # 预热
    async with pool.acquire() as conn:
        for c in collections:
            await conn.fetch(queries[c], qvec, 3)

    # --- 串行延迟（单个连接逐条查）---
    serial_times = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        async with pool.acquire() as conn:
            for c in collections:
                await conn.fetch(queries[c], qvec, 3)
        serial_times.append((time.perf_counter() - t0) * 1000)

    # --- 并发延迟（池中 4 条连接同时查）---
    parallel_times = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        async with pool.acquire() as c1, pool.acquire() as c2, \
                pool.acquire() as c3, pool.acquire() as c4:
            await asyncio.gather(
                c1.fetch(queries["chapters"], qvec, 3),
                c2.fetch(queries["characters"], qvec, 3),
                c3.fetch(queries["world_settings"], qvec, 3),
                c4.fetch(queries["plot_events"], qvec, 3),
            )
        parallel_times.append((time.perf_counter() - t0) * 1000)

    def stats(ts: list[float]) -> tuple[float, float, float]:
        ts_sorted = sorted(ts)
        return ts_sorted[len(ts_sorted) // 2], ts_sorted[0], ts_sorted[-1]

    s_med, s_min, s_max = stats(serial_times)
    p_med, p_min, p_max = stats(parallel_times)
    saving = s_med - p_med

    print("\n=== 真实 DB 基准（RAG 4 集合, 每集合 1000 行, dim=1536, HNSW）===")
    print(f"串行 {n_runs} 次: 中位 {s_med:.1f}ms | min {s_min:.1f}ms | max {s_max:.1f}ms")
    print(f"并发 {n_runs} 次: 中位 {p_med:.1f}ms | min {p_min:.1f}ms | max {p_max:.1f}ms")
    print(f"收益: 中位省 {saving:.1f}ms ({100*saving/s_med:.0f}%)")

    # --- 单查询 HNSW 延迟（大数据量缩放验证） ---
    print("\n=== HNSW 单查询延迟（10 次）===")
    for n in (3000,):
        # 临时把 chapters 扩充到 3000 行验证容量伸缩
        rng2 = random.Random(99)
        async with pool.acquire() as conn:
            for i in range(PER_COLLECTION, n):
                await conn.execute(
                    "INSERT INTO chapters (novel_id, chapter_index, title, content_text, summary, word_count, status, embedding) "
                    "VALUES (1,$1,$2,$3,$4,$5,'active',$6)",
                    i, f"C{i}", "x" * 5, f"S{i}", 10 + i, str(_rand_vector(i, rng2)),
                )
            times = []
            for _ in range(10):
                t0 = time.perf_counter()
                await conn.fetch(queries["chapters"], qvec, 3)
                times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        print(f"  chapters {n} 行: 中位 {times[len(times)//2]:.2f}ms | min {times[0]:.2f}ms")


async def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "both"
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=4, max_size=8)
    try:
        if action in ("seed", "both"):
            async with pool.acquire() as conn:
                await seed(conn)
        if action in ("bench", "both"):
            await bench(pool)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
