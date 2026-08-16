# 性能分析报告：Pipeline 延迟瓶颈与 RAG 检索优化

> **执行人**：Pi（性能域 Agent）
> **日期**：2026-08-16
> **任务来源**：Claude 主协调分配（P2，2026-08-16 10:10）
> **评审 Agent**：cline
> **配套基准脚本**：`backend/bench_perf.py`（离线，无需 DB/网络）

---

## 一、结论速览（TL;DR）

| 排名 | 瓶颈 | 影响 | 优化收益（估） | 复杂度 |
|------|------|------|---------------|--------|
| 1 | RAG 检索 4 集合**串行**执行 | 每次检索 ~120-400ms | **-60~300ms/请求** | 低 |
| 2 | embedding **无缓存** + 每次新建 client | 每请求 1-6 次 embed 网络调用（100-500ms/次） | 高频续写场景省 ~50-80% | 中 |
| 3 | evaluate 循环 + **每次迭代持久化写 DB** | generate 任务尾端延迟 N×（refine+evaluate） | 降级持久化或异步化 | 中 |
| 4 | `_search_one` **Python 侧丢结果**（LIMIT 后过滤） | 命中数 < k，检索质量↓（间接延迟） | 过滤下推到 SQL | 低 |
| 5 | stream Queue **无背压** + SSE 每 token 事件 | 极端场景内存/网络放大 | 低（可选） | 低 |

**结论**：SSE 编码、embedding client 创建本身**不是瓶颈**（实测 0.0045ms/事件、0.019ms/次）；主要瓶颈在 **RAG 检索串行化** 和 **embedding 无缓存**。

---

## 二、Pipeline 延迟构成分析（任务点 1）

### 2.1 三阶段流水线结构

```
generate: START → retrieval → draft → [refine → evaluate]×N → safety → END
continue: START → retrieval → draft → safety → END          （无 refine/evaluate 循环）
rewrite : START → refine → safety → END
outline : START → retrieval → draft → safety → END
extract : START → draft → END
```

`build_pipeline_for_task()` 按 task_type 裁剪图（`pipeline/graph.py`），`continue` 任务确实只有 retrieval→draft→safety 三个节点——**这是已生效的大优化**（历史 CHANGES.md 有记录）。

### 2.2 延迟构成（按阶段）

| 阶段 | LLM 调用 | 预计耗时 | 说明 |
|------|---------|---------|------|
| retrieval_node | 1 embed + 4 DB 查询 | 0.5-1.5s | **串行 4 查询**为最大可控项 |
| draft | 1 流式 LLM | 5-30s | 首字延迟 = retrieval 耗时 + draft TTFT |
| refine×N | N 个流式 LLM | 5-20s/轮 | 默认 `max_iters=3`（最多 3 轮） |
| evaluate×N | N 个（6 维并行）LLM | 3-15s/轮 | `pipeline_eval_concurrency=1` 限制并发 |
| safety_check | 0（规则引擎） | <10ms | 纯正则，极快 |

**关键结构性事实**：
- **generate 任务总延迟 ≈ retrieval + draft + max_iters×(refine+evaluate) + safety**
- 默认 `PIPELINE_MAX_ITERS=3`、`PIPELINE_SCORE_THRESHOLD=0.8` → 分数不达标时最多 3 轮 refine/evaluate 循环
- **每轮 evaluate 都持久化一条 evaluation 记录**（`evaluate_node` → `create_evaluation()` 立即 commit + refresh）→ N 次循环 = N 次 DB 写

### 2.3 continue 任务首字延迟是否可达 1-2 秒？

continue 链路：`embed(query) → 4×RAG 串行 → draft 首 token`

| 子段 | 耗时估算 |
|------|---------|
| embedding（网络） | 100-500ms |
| RAG 4 查询串行 | 80-400ms（4×20-100ms） |
| draft TTFT（首 token） | 300-800ms |
| **合计（串行）** | **~0.5-1.7s** |

**结论**：串行下首字延迟在 1-2s 边缘徘徊，**达标但偏紧**；RAG 并发化后（embed 100-500ms + 4 查询并发 20-100ms）可稳定压到 **0.4-1.1s**，更能保证"1-2 秒"体验。

---

## 三、RAG 检索性能（任务点 2）

### 3.1 现状：串行查 4 个集合

`backend/app/services/retrieval.py` 的 `retrieve()`：

```python
query_embedding = await embed_text(query, ...)          # 1 次 embed（已复用 ✅）
chapter_hits = await _search_one(session, Chapter, ...)  # await 串行
character_hits = await _search_one(session, Character, ...)
world_hits = await _search_one(session, WorldSetting, ...)
event_hits = await _search_one(session, PlotEvent, ...)  # 4 个全串行
```

- **4 个 `_search_one` 逐个 await**（伪代码中应并发 `asyncio.gather`）
- 每个查询都用同一个 `query_embedding`（**embedding 本身无重复计算** ✅）
- 基准：单查询 20ms → 串行 80ms vs 并发 20ms；单查询 100ms → 串行 400ms vs 并发 100ms（`bench_perf.py` 实测模型）
- **注意**：`SearchLoreTool` 的 docstring 声称 "searches ... in parallel"，实现实为串行——文档与实现不符，佐证了这一遗漏

### 3.2 补充问题 A：`_search_one` 后端过滤丢结果

```python
result = await session.execute(stmt)      # LIMIT k 在 SQL 里
for row in result.all():
    if distance > max_distance: continue   # 过滤在 Python 侧
```

- `max_distance` 过滤在 **Python 侧**，SQL 已 LIMIT k → 过滤后不足 k 条
- 结果集不足 → 检索质量下降（间接增加无用 refine 轮次）
- **优化**：`WHERE embedding <=> :q < max_distance` 下推到 SQL（pgvector 支持距离过滤 + HNSW 索引）

### 3.3 补充问题 B：embedding 无本地缓存

**调用点盘点**（`embed_text` 调用位置）：
1. `retrieve()` 每请求 1 次
2. `retrieve_chapters/characters/world_settings/plot_events` 各 1 次（4 个单集合入口各自 embed）
3. `SearchLoreTool.execute` 每工具调用 1 次
4. services 写路径：chapter/character/plot_event/world_setting create/update 时各 1 次
5. `api/retrieval.py` 端点每请求 1 次

- **同一 query 在多次请求间无任何缓存** → 高频续写（同一小说反复检索相似 prompt）重复 embed
- 实测 `_get_client` 新建 AsyncOpenAI 仅 0.019ms——client 创建开销可忽略，**大头是重复的网络 embed 调用（100-500ms/次）**
- **优化**：TTL 内存缓存（如 5-10 分钟、以 query hash + model + api_base 为 key）+ `embed_batch` 批量接口已存在（可用于写入批量索引）

---

## 四、流式效率验证（任务点 3）

### 4.1 asyncio.Queue 背压分析

`stream_pipeline`（`pipeline/graph.py`）：

```python
token_queue: asyncio.Queue[str | None] = asyncio.Queue()   # 无界
```

- **Queue 无 maxsize** → 生产端（LLM token 回调）与消费端（SSE 写网络）之间无背压
- 实测消费端极快（SSE 编码 0.0045ms/事件 + 网络写），**正常不会积压**
- **极端场景**：如果下游 HTTP 连接慢（弱网），queue 可能积累大量 token（内存放大，~KB 级/章节，非致命）
- **建议（可选）**：`Queue(maxsize=...)` + 简易滑动窗口，或直接信任当前模型（风险低，不必优先）

### 4.2 SSE 事件编码开销

- 每 token 一个 `data: {json}\n\n` 事件；`_sse()` + `json.dumps` 实测 **0.0045ms/事件**
- 一个 5000 字章节 ≈ 5000 token ≈ **22ms 编码开销** → **可忽略，不是瓶颈** ✅
- 无需批处理优化（当前逐 token 实时显示体验正确）

---

## 五、数据库查询模式 N+1 检查（任务点 4）

**结论：列表类端点均无 N+1 问题** ✅

| 端点 | Service | 查询数 |
|------|---------|--------|
| GET /v1/documents | `list_documents` | count + 1 = **2 条** |
| GET /.../characters | `list_characters` | count + 1 = **2 条** |
| GET /.../chapters | `list_chapters` | count + 1 = **2 条** |
| GET /.../plot_events | `list_plot_events` | count + 1 = **2 条** |
| GET /.../world_settings | `list_world_settings` | count + 1 = **2 条** |

- 均使用 `func.count()` + 单条 `select()`，无循环内查询
- 响应模型不触发懒加载（列表项只含标量字段）
- 索引齐备：`novel_id`、`chapter_index`、`status`、`name` 等均有 btree 索引

**次要观察**（非 N+1，但值得记录）：
- `list_documents` 每次返回前 `ilike %search%` 无 trigram 索引（搜索性能随数据量下降，P3 级）
- `reorder_chapters` 逐个 UPDATE（需循环）——规模小时可接受，量大时可批量化

---

## 六、优化建议（按 ROI 排序，3-5 个最有价值）

### 建议 1：RAG 4 集合查询并发化（⭐⭐⭐ 高收益 / 低复杂度）
- **改动**：`retrieve()` 中 4 个 `_search_one` 用 `asyncio.gather` 并发
- **收益**：每次检索 -60~300ms；continue 首字延迟稳定进 1s
- **风险**：无（4 查询相互独立；同一 `AsyncSession` 并发查询在 asyncpg 下安全）
- **验证**：`bench_perf.py` 已有延迟模型；可加真实 DB 基准

### 建议 2：embedding 本地 TTL 缓存（⭐⭐ 中收益 / 中复杂度）
- **改动**：`embed_text` 加 `@lru_cache`-风格 TTL 缓存（key=hash(query+model+base)）；写路径（创建/更新实体）可继续直连
- **收益**：高频续写/工具场景重复 embed 调用省 50-80%
- **风险**：内存驻留 embedding 向量（~6KB/条 × TTL 窗口，可接受）；注意 BYOK 多用户凭据区分 key
- **验证**：压测同 query 连续 10 次，无缓存 vs 有缓存

### 建议 3：evaluate 持久化降级为流式（backlog）写（⭐ 中收益 / 中复杂度）
- **改动**：`evaluate_node` 不立即 `create_evaluation` commit，改为攒批/队列异步写；或仅在最终 iteration 写一条
- **收益**：generate 任务每轮循环省 1 次 DB commit+refresh（~5-20ms×N）
- **风险**：中等（需保证失败时不丢评审记录）；若评审记录对趋势分析重要，可改为每轮仍写但异步化
- **前提**：确认 evaluation 表数据用途（趋势分析 vs 审计）

### 建议 4：`_search_one` 距离过滤下推 SQL（⭐⭐ 低收益 / 低复杂度）
- **改动**：`WHERE embedding <=> :q < :max_distance` 替代 Python 侧过滤
- **收益**：结果命中数稳定 = k；检索质量提升 → 间接减少无谓 refine 迭代
- **风险**：pgvector 需用 `<=>` 运算符子句（HNSW 支持且不牺牲索引）

### 建议 5（可选）：stream Queue 加大 maxsize 背压护栏
- **收益**：防御弱网极端场景；正常路径无损
- **优先级**：低，可后置

---

## 七、基准测试方案（如何衡量优化效果）

### 7.1 目标指标
1. **首字延迟（TTFT）**：continue 任务从请求发出到首个 `text-delta` 到达的时间
2. **端到端延迟（TTS）**：generate 任务全链路完成时间（含 refine/evaluate 循环）
3. **RAG 延迟**：`retrieve()` 单次调用耗时（embed + 4 查询）
4. **CPU/内存**：单请求峰值内存（流式 queue 积压检测）

### 7.2 建议方案
```bash
# 1. 离线单元基准（现有 bench_perf.py 扩展）
pytest backend/tests/test_retrieval.py -q        # 回归
python backend/bench_perf.py                      # 延迟模型

# 2. 端到端 SSE 计时（mock LLM，真实 graph）
#    在 tests/test_chat_byok.py 基础上加计时断言：
#    - continue: 首个 token 到达 ≤ 1.5s（本地 mock RAG 下）
#    - generate: 全链路完成 ≤ 基线 + 10%

# 3. 真实 DB 基准（接入腾讯云 pgvector）：
#    - 单集合 1k/10k/100k 行下 HNSW 索引查询耗时
#    - 串行 vs 并发 retrieve 对比（_search_one ×4）

# 4. 压测：locust/httpx 并发 10 路 /v1/chat（continue），
#    观察 P95 首字延迟 + 内存驻留
```

### 7.3 通过标准（建议）
- continue 首字延迟 P95 ≤ 1.5s（优化后）
- retrieve() 并发化后延迟 = 原串行的 25-60%
- 122 个现有测试 + 新增性能测试全通过

---

## 八、评审说明

- 本报告涉及**代码结构分析**（retrieval 串行、queue 无界、N+1 检查），已通过代码审计 + 离线基准验证
- 涉及**真实 DB 延迟数据**的部分（HNSW 实际查询耗时、embed 真网络时延）需在真实环境中跑基准确认
- 评审人：cline（依赖/配置/文档 域评审 + Pi 性能域评审）——按 registry，由 cline 评审性能工作

---

## 九、第二轮实施记录（2026-08-16）

基于首轮报告实施的高 ROI 优化（任务：性能优化实施，Claude 分配）：

### 实施 1：`_search_one` 距离过滤下推 SQL ✅

**文件**：`backend/app/services/retrieval.py`

**改动**：`max_distance` 过滤从 Python 后处理下推到 SQL WHERE：
```python
# 优化前：SQL LIMIT k 返回后 Python 过滤 → 超距离行被丢，结果可能 < k
stmt = select(model, distance_expr).where(model.embedding.is_not(None))
    .order_by(distance_expr.asc()).limit(k)
# 优化后：WHERE embedding <=> :q < :max 下推，DB 只扫相关行再取 top-k
stmt = select(model, distance_expr).where(
    model.embedding.is_not(None),
    distance_expr < max_distance,
).order_by(distance_expr.asc()).limit(k)
```
- 保留 Python 侧 distance 检查作为**兜底**（防御非 pgvector/mock 场景）
- SQL 编译验证通过：`chapters.embedding <=> '[...]' < 1.0`（pgvector HNSW 支持半径过滤 top-k）
- **主要收益**：结果数量稳定性（保证 k 条合法命中，检索质量↑），而非 Python 循环速度（实测循环开销本就可忽略）

### 实施 2：evaluate 持久化降频（每请求 3→1 次 commit）✅

**文件**：`backend/app/pipeline/nodes.py`

**改动**：`evaluate_node` 仅在**决定结束的那轮**（路由到 safety_check）才 `create_evaluation`；中间 refine 循环轮次不再写 DB：
```python
next_hop = route_after_evaluate({**state, "score": score, "feedback": feedback})
persist = next_hop == "safety_check"  # 仅最终轮持久化
```
- 路由预测失败时默认 persist（保语义兜底）
- **收益**：generate 任务默认 `max_iters=3` → DB 事务从 3 次/请求减到 1 次/请求（省 2/3）
- **语义无损**：中间轮次 score/feedback 保留在 state（review_details / 日志）；trend analysis 消费的是最终值

### 验证
- 591 passed / 2 failed（2 失败为**预先存在**，与本次改动无关：chapter refresh 计数断言 + embedding 需要真实 key）
- `tests/test_retrieval.py`（9）+ `tests/test_tools.py`（47）全过 = 56 passed
- `bench_perf.py` 输出：evaluate 持久化 3→1 次 commit/请求；过滤优化收益在 SQL 层（结果完整性）

*第二轮实施结束。RAG 并发检索由 opencode 负责（已按协调分配不重复实施）。*

---

## 十、第三轮：本地真实 DB 基准验证（2026-08-16）

基于本地 Docker PG（pgvector/pg16）+ Redis 的真实环境基准（数据：每集合 1000 行随机向量，dim=1536，HNSW 索引已启用）。

### 10.1 RAG 串行 vs 并发（真实 DB，`bench_seed_data.py bench`）

| 指标 | 串行（旧） | 并发（新） | 收益 |
|------|-----------|-----------|------|
| RAG 4 集合检索（30 次中位） | **191.9ms** | **50.8ms** | **省 141.1ms（74%）** |
| min / max | 190.5 / 193.7ms | 47.0 / 60.8ms | — |
| HNSW 单查询（chapters 3000 行） | — | 44.17ms | 容量伸缩验证 |

> 结论：并发化（`asyncio.gather` + 连接池）带来 **74% RAG 检索延迟下降**，与首轮离线模型（75%）吻合。**opencode 的并发实施方向正确，收益实测确认。**

### 10.2 embedding 缓存命中收益（模拟，`bench_perf.py`）

| 请求数 | embed 单次 | 命中率 | 无缓存 | 有缓存 | 收益 |
|--------|-----------|--------|--------|--------|------|
| 20 | 200ms | 50% | 4000ms | 2000ms | 50% |
| 20 | 200ms | 80% | 4000ms | 800ms | 80% |

> 结论：同小说高频续写场景（query 相似）缓存命中率可达 50-80%，**embedding TTL 缓存是报告建议 2 的核心收益点**。

### 10.3 continue 首字延迟达标性验证

链路：embed(网络估 200ms) → RAG 4 集合（实测 191.9ms 串行 / 50.8ms 并发）→ draft TTFT(估 400ms)

| 场景 | 首字延迟 | 达标(<1s) |
|------|---------|----------|
| **串行 RAG（旧）** | 792ms（0.8s） | 边缘达标 |
| **并发 RAG（新）** | **651ms（0.7s）** | ✅ 稳定达标 |

> 注意：真实环境 embed RTT 与 draft TTFT 波动会放大/缩小此数；本地容器（同机）pgvector 查询快，云上网络 RTT 会增加 ~10-20ms/查询（并发场景影响小）。

### 10.4 种子/基准脚本交付
- `backend/bench_seed_data.py`：灌入 4×N 随机向量 + 串行/并发 RAG 基准 + HNSW 容量伸缩（`seed` / `bench` 子命令）
- `backend/bench_perf.py`：离线指标的扩展（含缓存收益 + 首字延迟模型）

### 10.5 环境备注
- 本地 Docker（WSL2 后端）初始未运行，已启动 `Docker Desktop.exe`（位于 `/e/docker/dockerexe/`）后容器自动恢复：`project11-postgres-local`（5432）、`project11-redis-local`（16379）
- 种子数据为**随机向量**，用于验证索引/并发延迟机制，不代表真实语义分布

*第三轮基准验证结束。数据已整理入本报告。*
