# Project11 — AI 小说创作平台

AI 小说创作平台：三阶段 LLM 流水线（草稿 → 精修 → 评估）+ 实时流式输出 + BYOK 多 provider + RAG 记忆检索 + 多 Agent 系统。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11 + FastAPI + LangGraph + LiteLLM |
| LLM | DeepSeek-V4-Flash (草稿) → Qwen-Max (精修) → Claude Sonnet (评估)，用户可 BYOK 自选 |
| 数据库 | PostgreSQL 16 + pgvector + Redis（**本地 Docker 容器**） |
| 前端 | Next.js 14 + TailwindCSS + Tiptap + Vercel AI SDK v5 |
| 依赖管理 | **uv**（Python 虚拟环境 + 依赖锁定） |
| 部署 | 本地：直接进程运行 + Docker 容器（仅数据库）；服务器：见 [deploy/README.md](deploy/README.md) |

> **本地环境**：PostgreSQL 16 + Redis 通过 `docker-compose.local.yml` 跑在 Docker 容器里（仅 2 个容器，轻量）。后端和前端用本地进程运行。
> **Python 环境**：全部通过 `uv` 管理（`backend/pyproject.toml`），虚拟环境在 `backend/.venv`。

## 核心特性

### 🔴 P0 已解决

- **task_type 智能路由**：根据任务类型自动选择最少的 pipeline 阶段。续写只跑 draft + safety（~2秒），不再跑完整 refine→evaluate 循环
- **真流式输出**：LLM 逐 token 生成时实时推送到前端，用户从第 1 秒起就能看到文字出现，不再白屏等待
- **阶段级降级**：任一 LLM 阶段失败时自动跳过并标注，pipeline 继续运行直到输出结果

### 🟠 P1 已解决

- **选中文字操作**：选中编辑器中的文字后点击 AI 工具，直接对选中内容进行扩写/重写/降AI
- **RAG 上下文注入**：refine 阶段也注入角色/世界观/剧情记忆，不再"盲改"
- **上下文扩展**：RAG 检索从 top_k=3 扩大到 5，输出限制从 4000→8000 字符
- **大纲关联题目**：大纲生成时自动携带小说标题，不再生成与题目无关的内容
- **生成正文注入大纲**：生成正文和续写时自动附带已保存的大纲作为参考上下文
- **路由标签清理**：后端 `_extract_topic()` 剥离 `[novel:N]` 和 `[task:TYPE]` 标签，LLM 只看到干净的用户 prompt

### 🟡 P2 已解决

- **BYOK 快速配置模板**：3 种预设（DeepSeek+Qwen+Claude / 全 OpenAI / 全 DashScope），一键填充
- **推荐 model 下拉**：每个阶段旁边提供推荐模型列表
- **连接测试**：配置完 API Key 后可直接测试连接，不用发真实消息验证
- **阶段级错误信息**：错误信息精确到哪个阶段（draft/refine/evaluate）出了问题
- **评估超时保护**：每个评估维度 30 秒超时，单个维度失败不影响其他维度
- **refine 循环上限**：最多 5 次迭代，防止无限震荡

### 🟢 前端体验

- **闪烁光标**：流式生成时文字末尾显示闪烁光标，视觉反馈清晰
- **打字指示器**：等待首个 token 时显示三点动画
- **替换选中**：选中文字后可直接用 AI 输出替换，不用手动删除
- **保存门槛降低**：只需配好 1 个阶段即可保存，不必三阶段全填
- **大纲状态清理**：应用大纲后自动清除 AI 面板状态，防止残留文本被误插入正文

---

## 目录

```
project11/
├── backend/              # FastAPI + LangGraph 后端
│   ├── alembic/          # 数据库迁移
│   ├── app/
│   │   ├── agents/       # 角色化 Agent（Plotter/Character/Editor/Safety）
│   │   ├── api/          # REST 端点（chat/documents/chapters/...）
│   │   ├── eval/         # 多维度评估矩阵
│   │   ├── llm/          # LLM 客户端（litellm 封装 + embedding）
│   │   ├── models/       # SQLAlchemy ORM
│   │   ├── pipeline/     # LangGraph 三阶段流水线（核心）
│   │   ├── planner/      # DAG 编排器 + 任务模板
│   │   ├── safety/       # 内容安全规则引擎
│   │   ├── schemas/      # Pydantic 模型
│   │   ├── services/     # 业务逻辑层
│   │   └── tools/        # Agent 工具注册表
│   ├── tests/
│   ├── pyproject.toml    # uv 依赖声明（唯一权威）
│   └── requirements.txt  # 兼容旧工具（内容与 pyproject.toml 同步）
├── frontend/             # Next.js 14 前端
│   └── src/
│       ├── app/          # 页面路由
│       ├── components/   # UI 组件
│       ├── hooks/        # React hooks
│       └── lib/          # 工具函数 + 类型定义
├── deploy/               # 服务器部署配置
├── docker-compose.yml    # 服务器全栈（含 nginx）
└── docker-compose.local.yml  # 本地仅数据库（PG + Redis）
```

---

## 一、首次配置（从零开始）

> 假设：Windows 本地开发。需要 [uv](https://docs.astral.sh/uv/) 和 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（WSL2 后端，用于跑 PG/Redis 容器）。

### 前置检查

```powershell
uv --version        # 应有输出，如 uv 0.x.x
docker info         # 应显示 Server 信息（Docker Desktop 已启动）
```

### 步骤 1：启动本地数据库（Docker 容器）

```powershell
# 在项目根目录，启动 PostgreSQL 16 + pgvector 和 Redis 两个容器
docker compose -f docker-compose.local.yml up -d

# 验证两个容器都 healthy
docker ps
# 期望看到 project11-postgres-local 和 project11-redis-local 均 (healthy)
```

> 首次启动会自动拉取镜像（如网络慢，可配置 Docker 镜像加速器）。数据持久化在 Docker 卷 `pg_data` / `redis_data`，删除容器不丢数据。

### 步骤 2：配置后端环境

```powershell
cd backend
Copy-Item .env.example .env
# 编辑 .env 填入真实 API Key（详见 .env.example 注释）
# DATABASE_URL 和 REDIS_URL 已默认指向 localhost:5432 / 16379，无需修改
```

### 步骤 3：用 uv 构建后端虚拟环境并安装

```powershell
cd backend
uv sync            # 创建 .venv 虚拟环境 + 按 pyproject.toml 安装全部依赖 + 生成 uv.lock
```

> `uv sync` 是 uv 的标准工作流：自动创建 `backend/.venv`，安装 pyproject.toml 声明的依赖（含 dev 组测试依赖），并锁定版本到 `uv.lock`。之后日常都用 `uv sync` / `uv run`，无需手动激活虚拟环境。

### 步骤 4：初始化数据库（迁移）

```powershell
cd backend
uv run alembic upgrade head
```

> `uv run` 会在虚拟环境中执行命令，无需手动 activate。

### 步骤 5：配置前端

```powershell
cd frontend
# 创建 .env.local（后端地址）
echo NEXT_PUBLIC_BACKEND_URL=http://localhost:8000 > .env.local
npm install
```

### 步骤 6：启动

```powershell
# 终端 1: 后端（uv 虚拟环境中运行）
cd backend && uv run uvicorn app.main:app --reload --port 8000

# 终端 2: 前端
cd frontend && npm run dev
```

访问 http://localhost:7421 → 点击 ⚙ 配置 API Key → 开始写作。

---

## 二、日常启动

```powershell
# 终端 0（如容器已停止）: 启动数据库
docker compose -f docker-compose.local.yml up -d

# 终端 1: 后端（uv 虚拟环境中运行，--reload 自动重载）
cd backend && uv run uvicorn app.main:app --reload --port 8000

# 终端 2: 前端
cd frontend && npm run dev
```

**停止数据库**：
```powershell
docker compose -f docker-compose.local.yml down    # 停止并删除容器（数据卷保留）
docker compose -f docker-compose.local.yml down -v # 连数据卷一起删（彻底重置）
```

**清理虚拟环境重装**：
```powershell
cd backend
rm -r .venv          # 删除虚拟环境
uv sync              # 重新构建
```

---

## 三、BYOK 配置指南

### 快速配置（推荐新用户）

1. 打开设置对话框
2. 点击预设按钮（如"推荐：DeepSeek + Qwen + Claude"）
3. 只需填写 API Key，api_base 和 model 已自动填充
4. 点击"测试连接"验证
5. 保存

### 自定义配置

每个阶段可指向不同的 provider：

| 阶段 | 推荐模型 | 用途 |
|------|---------|------|
| Draft 草稿 | deepseek-v4-flash / gpt-4o-mini | 低成本生成初稿 |
| Refine 精修 | qwen-max / gpt-4o | 中文编辑能力强 |
| Evaluate 评估 | claude-sonnet-4-5 / gpt-4o | 推理稳定，T=0 |
| Embedding | text-embedding-3-small / text-embedding-v4 | RAG 记忆检索 |

---

## 四、AI 工具使用

编辑器右侧提供 6 个 AI 工具：

| 工具 | 说明 | Pipeline 路由 |
|------|------|--------------|
| 📋 生成总纲 | 为整部小说生成大纲结构 | outline（仅 draft + safety） |
| ✨ 生成正文 | 根据总纲生成正文段落 | generate（完整 pipeline） |
| ✍️ 续写 | 从当前末尾续写下文 | continue（仅 draft + safety） |
| 📝 扩写 | 扩写选中或末尾段落 | rewrite（仅 refine + safety） |
| 🔄 重写 | 重写当前段落 | rewrite（仅 refine + safety） |
| 🧹 降AI | 降低 AI 检测率 | polish（仅 refine + safety） |

**上下文注入**：AI 工具自动注入以下上下文，确保生成内容与小说主题一致：
- **小说标题**：大纲生成时携带标题，不再"空穴来风"
- **大纲内容**：生成正文和续写时自动附带已保存的大纲作为参考
- **编辑器文本**：续写/扩写/重写使用当前章节末尾 3000 字作为上下文
- **选中文字**：扩写/重写/降AI 针对选中内容而非全文

**大纲应用流程**：点击"应用大纲"后自动执行：
1. 大纲保存到文档 metadata
2. 自动识别并创建章节（正则匹配 `第X章` / `1.` 格式）
3. 自动提取角色、世界观、剧情事件（通过独立的 `extract` 任务）
4. 清除 AI 面板状态，防止残留文本被误插入正文

---

## 五、架构设计

### 5.1 Pipeline 架构

```
用户输入 → task_type 路由
  │
  ├─ "generate": retrieval → draft → refine → evaluate → [loop] → safety
  ├─ "continue": retrieval → draft → safety  （快速，~2秒出首字）
  ├─ "rewrite":  refine → safety
  └─ "outline":  retrieval → draft → safety
```

**真流式实现**：draft_node 和 refine_node 使用 `stream=True` 调用 LLM，每个 token 通过 `on_token` 回调放入 asyncio.Queue，`stream_pipeline` 实时 yield 给前端。前端 `useChat` 逐 token 更新 UI。

**阶段级降级**：evaluate_node 失败时返回 `fallback_mode=True, score=0.5`，pipeline 继续到 safety_check 而非整体崩溃。

**Prompt 上下文注入**：`buildPrompt()` 根据工具类型动态组装上下文（小说标题、大纲内容、章节文本、选中文字），`_extract_topic()` 在传给 LLM 前剥离内部路由标签 `[novel:N]` 和 `[task:TYPE]`。

### 5.2 BYOK 三阶段独立凭证

前端通过 `X-Provider-Config` 头部上传 `ProviderConfig { draft, refine, evaluate, embedding? }`，每个 StageConfig 各自携带 `api_base / api_key / model / extra_headers`。后端 SSRF 校验 api_base，key 在日志中脱敏。

### 5.3 RAG 记忆检索

四个记忆集合（章节/角色/世界观/剧情事件）均带 pgvector 向量列。retrieval_node 在 draft 前执行语义检索，结果注入 draft_node 和 refine_node 的系统提示词。

### 5.4 多 Agent 系统

| 模块 | 职责 |
|------|------|
| `agents/plotter.py` | 大纲生成 / 世界观构建 / 一致性检查 |
| `agents/character.py` | 角色档案生成 |
| `agents/editor.py` | 章节写作 / 精修 / 最终润色 |
| `planner/orchestrator.py` | DAG 编排器，按拓扑序执行子任务 |
| `eval/matrix.py` | 6 维并行评估（连贯性/角色一致性/文笔/情节/世界观/跨章节） |
| `safety/` | 规则引擎 + LLM 内容安全审核 |

---

## 六、API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat` | 流式聊天（SSE），支持 task_type 路由 |
| POST | `/v1/chat/test` | 连接测试，验证 API Key 和模型 |
| GET | `/health` | 健康检查 |
| CRUD | `/v1/documents/...` | 文档管理 |
| CRUD | `/v1/documents/{id}/chapters/...` | 章节管理 |
| CRUD | `/v1/documents/{id}/characters/...` | 角色管理 |
| CRUD | `/v1/documents/{id}/world-settings/...` | 世界观管理 |
| CRUD | `/v1/documents/{id}/plot-events/...` | 剧情事件管理 |
| POST | `/v1/documents/{id}/retrieve` | RAG 语义检索 |

---

## 七、验证清单

| 项 | 期望 |
|---|---|
| `docker compose -f docker-compose.local.yml ps` | 两个容器均 healthy |
| `curl http://localhost:8000/health` | `{"status":"ok"}` |
| 浏览器 http://localhost:7421 | 显示小说编辑器界面 |
| 配置 BYOK → 测试连接 | 显示 ✅ 连接成功 |
| 点击"续写" | ~1-2 秒后文字逐字出现，带闪烁光标 |
| 选中文字 → 扩写 | 只处理选中内容 |
| 评估阶段 Key 无效 | 提示"evaluate: API Key 无效"而非笼统错误 |
| 点击"生成总纲" | 大纲内容与小说标题相关，不再是通用模板 |
| 点击"应用大纲" | 大纲保存、章节创建、实体提取成功，AI 面板清空 |
| 点击"生成正文" | AI 根据已保存大纲生成正文，而非凭空编写 |

---

## 八、常见问题

**Q: `docker compose` 拉取镜像失败？**
A: 国内网络需配置 Docker 镜像加速器（Docker Desktop → Settings → Docker Engine 加 `registry-mirrors`）。

**Q: 后端启动报 Redis 连接失败？**
A: 确认容器在跑：`docker compose -f docker-compose.local.yml ps`。如容器已停，先 `up -d`。

**Q: 续写还是白屏很久？**
A: 检查 task_type 是否正确传递。续写应走 `continue` 路由（仅 draft + safety），不走完整 pipeline。

**Q: 流式输出不实时？**
A: 确认后端 `stream_pipeline` 使用 `on_token` 回调而非旧的 4 字符切块。检查浏览器 Network 面板的 SSE 连接是否正常。

**Q: CORS 报错？**
A: 检查 `backend/.env` 的 `CORS_ORIGINS` 是否包含 `http://localhost:7421`。

**Q: 评估超时？**
A: 每个评估维度有 30 秒超时保护。超时的维度返回 0.5 分 fallback，不影响其他维度。

**Q: 生成正文时 AI 不按大纲写？**
A: 确认已先点击"应用大纲"保存大纲。生成正文时会自动从文档 metadata 读取大纲作为参考上下文。

**Q: `litellm` 安装失败？**
A: 确认 `pyproject.toml` 中 `litellm<1.91`。1.91+ 引入 Rust 组件。

**Q: 怎么重建虚拟环境？**
A: `cd backend && rm -r .venv && uv sync`。

---

## 九、贡献指南

- **AGENTS.md**：AI 协作原则见 [AGENTS.md](AGENTS.md)
- **提交规范**：Conventional Commits（`feat:` / `fix:` / `refactor:` / `docs:`）
- **测试要求**：新增功能必须带测试，覆盖率 ≥ 80%
- **关键约束**：不换框架、LiteLLM 是唯一 LLM 入口、`litellm<1.91` 硬性 pin、Python 依赖用 uv 管理

---

## 十、服务器部署

见 [deploy/README.md](deploy/README.md)（仅腾讯云服务器，本地开发不涉及）。
