# 变更说明

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
