# Agent Memory — Pi（性能域）

> 性能域 Agent 的持久化记忆。用于未来轮次快速恢复上下文，避免重复调查。
> 更新规则：每轮完成后将**新的性能结论/基准/环境事实**追加到对应章节；保留旧记录（追加不删改）。

---

## 1. 环境与基建（每次开工先确认）

| 项 | 状态 | 说明 |
|----|------|------|
| 工作树 | `E:/zxdevelop/.orca/worktrees/novel-agent/pi`，分支 `ZX466/pi` | 我的性能域工作树 |
| 后端 venv | `backend/.venv`（uv 创建，Python 3.11.15） | 用 `uv venv .venv --python 3.11` + `uv pip install -r requirements.txt` |
| 测试 | `cd backend && .venv/Scripts/python.exe -m pytest -q` | **基线 655 passed / 5 failed**（5 failed 全为 pre-existing：`nh3` 模块缺失，属 cline/kilo 依赖域） |
| 本地 Docker | Docker Desktop 在 `/e/docker/dockerexe/Docker Desktop.exe`（WSL2 后端） | 未运行时先启动它；容器：`project11-postgres-local`（pgvector/pg16, 5432）+ `project11-redis-local`（16379） |
| 远程 | origin=GitHub(ZX466)，gitee=Gitee(ZX666X) | **GitHub 网络不稳**（多次 Connection reset/超时）→ 先推 Gitee 保数据，再重试 GitHub |
| 前端 | `frontend/`，Next.js 14 + Tiptap | 验证用 `node node_modules/typescript/bin/tsc --noEmit` + `npx next lint`（node_modules 需时先 `npm install`） |

## 2. 协作工作流要点（talking.txt 机制）

1. **任务来源**：协调者（Claude）把 `[任务]` 写进我工作树的 `.orca/talking.txt`（或直接改文件后我 fetch/merge）
2. **接受**：先在 talking.txt 写 `[回复]` 状态「已接受」并提交（不提交会被 merge 挡）
3. **同步 main**：`git merge origin/main`——talking.txt 必然冲突（各 agent 板不同）→ **`git checkout --ours .orca/talking.txt` 保留我的 Pi 板**
4. **完成留痕**：`[回复]` 状态「已完成」+ 只记性能结论/基准/Git 状态/评审状态（Update Rule）
5. **提交推送**：conventional commits（`perf:`/`chore:`/`fix:`）；先 Gitee 后 GitHub；两条都推
6. **Update Rule**：每轮结束精简 talking.txt，只留当前任务/阻塞/最近验证/合并结果，删过程记录
7. **边界**：不越界其他能力域（安全→Codex、数据→opencode、接口→kilo、文档→cline）；发现其他域问题在报告/评审中标注，不自行修
8. **评审**：cline 评审我的性能域工作

## 3. 性能域关键结论（5 轮积累）

### RAG 检索
- **并发化收益 74%**（实测，真实 DB）：4 集合串行 191.9ms → `asyncio.gather` 并发 50.8ms（本地 1000 行/集合、dim=1536、HNSW）
- `_search_one` 距离过滤必须**下推 SQL**（`embedding <=> :q < :max` + `LIMIT k`），Python 侧兜底保留；否则 LIMIT 后过滤丢结果
- embedding **无缓存**：同 query 重复 embed（网络 100-500ms/次）；建议 TTL 缓存（命中 50-80% 省 50-80%）
- HNSW 索引已在 4 张表（`vector_cosine_ops`）

### Pipeline 延迟
- generate = retrieval + draft + max_iters×(refine+evaluate)；默认 `PIPELINE_MAX_ITERS=3`、`SCORE_THRESHOLD=0.8`、`EVAL_CONCURRENCY=1`
- evaluate 持久化：**只在最终轮（路由到 safety_check）写 DB**（原每轮 commit，3→1 次/请求）；用 `route_after_evaluate` 预测，失败兜底写
- continue 任务（retrieval→draft→safety）：首字延迟串行 0.79s → 并发 **0.65s < 1s 达标**
- 后端 `_extract_topic` 只取最后一条 user 消息（多轮对话不重放历史，TTFT 与轮数弱相关）✅ 已优化
- SSE 编码 0.0045ms/事件、embedding client 创建 0.019ms/次 → **都不是瓶颈**

### 编辑器 / 前端
- **EditorStats 曾每次 render 全量 `getText()` + 3 正则**（>100KB 每 keystroke 13.7ms）→ 已改：纯函数 `computeWordStats` + 300ms 防抖 + useMemo（**2.7x**）
- ⚠️ **cline P2 建议已采纳**：不要加 transaction 监听做 `getHTML()` 比较（O(n)/事务）；Tiptap `update` 事件已覆盖 setContent（dispatchTransaction → emit('update')）
- word_count 服务端：`_compute_word_count_incremental(old, new, old_count)` 用共同前缀/后缀只算变化段（100KB 尾部追加 **1.7x**）；等价性由参数化测试保证

### 统计看板（F6，kilo 实现）预算
- documents 表已有 word_count/created_at/updated_at
- 聚合禁拉 content_text/html 大文本列；单查询预算 ≤50-200ms；字数曲线需聚合方案

### PerfPulse 性能监控（R6，已实施）
- 后端：`nodes.py` 的 `@_timed(stage)` 装饰器写 `state["perf"][f"{stage}_ms"]`；开销 0.615us/节点（可忽略）
- `graph.py` run/stream_pipeline 加 `perf` dict 参数；`chat.py` 发 `{"type":"perf","data":{...}}` SSE 事件
- 前端：`PerfChatTransport`（自定义 transport 自解析 SSE）+ Chat.tsx 底部耗时区
- **坑**：AI SDK DefaultChatTransport 的 uiMessageChunkSchema 会**丢弃未知事件**（perf 无法透传）→ 必须自定义 transport 直接 fetch+解析 SSE；`reconnectToStream` 接口必须实现（不支持就返回 null）；ReadableStream start 回调里 `this` 丢失 → 用闭包捕获

## 4. 坑与教训

1. **asyncpg 单连接不能并发**：`asyncio.gather(conn.fetch...)` 报 "another operation in progress" → 必须用连接池（`create_pool`）模拟 SQLAlchemy 池化
2. **asyncpg 传 vector**：要传 `str(vec)`（`'[1.0,2.0]'`），不能传 list；jsonb 列传 JSON 字符串，不是 dict
3. **Windows 控制台 GBK**：跑含中文脚本加 `-X utf8`，或 open 文件带 `encoding='utf-8'`
4. **git 读 blob**：Windows msys 下 `git show 'main:.orca/talking.txt'` 会转义失败 → 用 `git ls-tree` + `git cat-file -p <blob>`
5. **npm 装前端后**：`package-lock.json` 若已入库且版本一致则 `git status` 不显示变化，无需提交
6. **gitignore 的 .claude/.codex/ 等**：是各 AI 工具私有目录，**不放共享记忆**；共享记忆放 `.orca/`（入库）
7. **merge main 时**：talking.txt、workflow 等各分支不同 → 默认 `--ours` 保留本分支板，再手动合并关键信息

---

*由 Pi 维护。追加新结论时保持节号结构，旧记录不删改。*
