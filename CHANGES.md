# 变更说明

## 2026-08-19：Round 5 创作工具轮 + 结构收敛

### Round 5（完善但简化创作流程，6/6 合入 main，tip `61182f7`）

| 功能 | 说明 | 提交 |
|------|------|------|
| R5-1 创作向导 CreationWizard | 设定→大纲→应用 三步一体引导，复用 useChat/createDocument/createChapter/extract，零新后端接口 | `a15efa8` |
| R5-2 创作配方卡 Recipe Cards | `docs/recipes/` 5 张卡（新书开写/续写/知识库/导出/换供应商）+ QUICKSTART 索引 | `bd69525` |
| R5-3 设定一致性哨兵 | RAG 检索比对角色历史设定，数值确定性比对（非 LLM），`consistency_checks` 表 + 迁移；含 P0 跨租户章节读取修复（`_chapter_text` 归属校验） | `9b29a7d`+`a323b7f`+`0bdd1ae` |
| R5-4 安心回溯 | 章节快照（save/AI 插入/整章替换/导出前自动）+ 版本历史面板（对比/恢复/删除），每章上限 50 | `8094a5d` |
| R5-5 多平台导出适配器 | `/v1/documents/{id}/export` 扩展 qidian/jj/zhihu/wechat 平台化 Markdown | `d44fb07` |
| R5-6 DocLite 超长文档零卡顿 | word_count 增量计算（1.7x）+ EditorStats 防抖/useMemo（2.7x） | `9bac060`+`f121290` |

**测试基线**：Redis 运行后 `746 passed / 1 skipped`（R6-3 并入后）。

### Round 6（进行中）

- R6-5 PerfPulse 性能自监控面板（pi）✅ 已合入：`@_timed` 采集 5 节点耗时（0.6us/节点）+ SSE perf 事件 + 前端状态栏，TDD 5 测试 | `81ebf35`
- R6-3 交稿雷达（codex）✅ 已实现待评审：`GET /v1/documents/{id}/safety-scan` 导出前隐私/版权/敏感表达预检（内容哈希缓存 + PII 证据脱敏 + 不阻塞导出），前端工具栏雷达按钮 + 导出前提示对话框（可忽略仍可导出）；顺带修复导出接口跨租户访问缺口；TDD 21 测试 | `3b71b96`+`95b865c`+`2b92c68`
- R6-1 章节脑图（Claude）/ R6-2 时间线图谱（opencode）/ R6-4 数据可移植网关（kilo）— 任务已定义（`.orca/proposals-r5.md`），待实施

### 结构收敛（2026-08-19）

- **仅保留 `main` 分支**（本地 + gitee + github）；5 个 `ZX466/*` 分支与工作树删除
- **各 Agent 记忆存档**：`.orca/agent-memory-pi.md`、`.orca/agent-memory-codex.md`、`AGENTS.md`（opencode）、`.orca/agent-boards/*-talking.txt`
- 后续协作直接在 main 上按能力域分工（见 `.orca/agent-registry.md`）

### 2026-08-17：Round 4（F1-F6 功能轮）

- F1 AI 编剧多轮对话（`task_type=assistant`，后端 `7796aca` + 前端 AssistantPanel）
- F3 导出（md/txt/epub，`91f0b24` 等）+ F6 统计看板（`4f518b3`，含 `0852923` cast 修复）
- F4 本地知识库（上传 magic 字节嗅探 + Redis 每 owner 限流 + 每作品存储配额，`e9bb92d`）
- 前端体验：显示设置 / 主题切换 / 专注按钮 / 编辑器完善
- 测试基线 649 → 721 → 726

---

## 2026-07-25：全面体验优化（Phase 1-4）

本次对 project11 进行了系统性的体验优化，覆盖 26 个问题中的 20 个核心问题。

### 一、P0 阻塞级问题（全部解决）

#### 1. task_type 智能路由
- **问题**：续写 100 字也跑完整 draft→refine→evaluate 循环，最坏 ~54,000 tokens
- **方案**：前端每个工具注入 `[task:TYPE]` 标记，后端按类型构建精简 pipeline
  - `continue`（续写）：仅 retrieval → draft → safety（跳过 refine/evaluate）
  - `rewrite`/`polish`（重写/降AI）：仅 refine → safety
  - `outline`（大纲）：仅 retrieval → draft → safety
  - `generate`（生成正文）：完整 pipeline
- **文件**：`pipeline/graph.py`, `api/chat.py`, `AIToolPanel.tsx`

#### 2. 真流式输出
- **问题**：全部 pipeline 跑完后才 4 字符切块发送，用户白屏 15-60 秒
- **方案**：
  - draft_node 和 refine_node 使用 `stream=True` 调用 LLM
  - 每个 token 通过 `on_token` 回调放入 asyncio.Queue
  - `stream_pipeline` 实时 yield 给前端 SSE
  - 前端 `useChat` 逐 token 更新 UI，文字逐字出现
- **文件**：`pipeline/nodes.py`, `pipeline/graph.py`, `pipeline/state.py`, `llm/clients.py`

#### 3. 阶段级降级
- **问题**：任一 LLM 阶段失败，整个 pipeline 失败
- **方案**：evaluate_node 失败时返回 `fallback_mode=True, score=0.5`，pipeline 继续到 safety
- **文件**：`pipeline/nodes.py`, `pipeline/state.py`

### 二、P1 高优先级（全部解决）

#### 4. RAG 上下文注入 refine
- **问题**：refine 完全忽略 RAG 上下文，进入循环后变"盲改"
- **方案**：refine_node 读取 `retrieved_context` 并注入系统提示词
- **文件**：`pipeline/nodes.py`

#### 5. 选中文字操作
- **问题**：AI 工具只能基于"最后 3000 字符"工作
- **方案**：
  - 编辑器跟踪选中文字（selectionUpdate 事件）
  - 扩写/重写/降AI 优先使用选中文字
  - 新增"替换选中文字"按钮
- **文件**：`AIToolPanel.tsx`, `editor/page.tsx`

#### 6. RAG 检索范围扩大
- k_per_collection 3→5，输出限制 4000→8000 字符
- **文件**：`pipeline/nodes.py`

### 三、P2 中优先级（全部解决）

#### 7. BYOK 快速配置模板
- 3 种预设（DeepSeek+Qwen+Claude / 全 OpenAI / 全 DashScope）
- 点击自动填充 api_base 和 model，用户只需填 api_key
- **文件**：`SettingsDialog.tsx`, `types.ts`, `config.py`

#### 8. 推荐 model 下拉
- 每个阶段旁提供推荐模型列表
- **文件**：`SettingsDialog.tsx`, `types.ts`, `config.py`

#### 9. 连接测试
- 新增 `POST /v1/chat/test` 端点
- 每个阶段添加"测试连接"按钮
- **文件**：`api/chat.py`, `SettingsDialog.tsx`

#### 10. 阶段级错误信息
- "API Key 无效，请检查配置中对应阶段的 Key 是否正确"
- "无法连接到 API Base URL，请检查网络和 URL 配置"
- "模型不存在，请检查模型名称是否正确"
- **文件**：`api/chat.py`, `pipeline/nodes.py`

#### 11. 评估超时保护
- 每个评估维度 30 秒超时，超时返回 0.5 分 fallback
- **文件**：`eval/matrix.py`

#### 12. refine 循环上限
- 硬上限 `_HARD_MAX_ITERS=5`，防止无限震荡
- **文件**：`pipeline/nodes.py`

#### 13. 保存门槛降低
- 从"三阶段全填才能保存"改为"至少一个阶段完整即可"
- **文件**：`SettingsDialog.tsx`

### 四、前端体验优化

#### 14. 闪烁光标
- 流式生成时文字末尾显示闪烁光标
- **文件**：`AIToolPanel.tsx`, `globals.css`

#### 15. 打字指示器
- 等待首个 token 时显示三点动画 + "正在生成…"
- **文件**：`AIToolPanel.tsx`

### 修改文件清单

| 文件 | 改动概述 |
|------|---------|
| `backend/app/pipeline/state.py` | 新增 task_type, on_token, fallback_mode, safety_passed 等字段 |
| `backend/app/pipeline/nodes.py` | 真流式 draft/refine, RAG 注入 refine, eval 降级, 硬上限 |
| `backend/app/pipeline/graph.py` | task_type 路由, asyncio.Queue 真流式, pipeline 缓存 |
| `backend/app/pipeline/__init__.py` | 导出 run_pipeline |
| `backend/app/api/chat.py` | task_type 提取, 连接测试端点, 阶段错误信息 |
| `backend/app/config.py` | BYOK presets, recommended_models |
| `backend/app/eval/matrix.py` | 维度级 30s 超时 |
| `backend/app/llm/clients.py` | _stream_with_retry, draft/refine 支持 stream=True |
| `frontend/src/lib/types.ts` | TaskType, BYOK_PRESETS, RECOMMENDED_MODELS |
| `frontend/src/components/AIToolPanel.tsx` | 选中文字, task_type 标记, 流式光标, 替换按钮 |
| `frontend/src/components/SettingsDialog.tsx` | 快速配置, 推荐下拉, 连接测试, 保存门槛 |
| `frontend/src/app/novels/[id]/editor/page.tsx` | 选中跟踪, 替换回调 |
| `frontend/src/app/globals.css` | blink 动画 |
| `README.md` | 全面重写 |

---

## 2026-07-20：代码整理与文档同步

详见 [CHANGES-2026-07-20.md](CHANGES-2026-07-20.md)（已归档）。
