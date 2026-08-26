# Project11 — AI 小说创作平台

三阶段 LLM 流水线（草稿 → 精修 → 评估）+ 实时流式输出 + BYOK 多 provider + RAG 记忆检索。

> **5 分钟跑起来**：[QUICKSTART.md](QUICKSTART.md) ｜ **服务器部署**：[deploy/README.md](deploy/README.md) ｜ **上手配方**：[docs/recipes/index.md](docs/recipes/index.md)

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11 + FastAPI + LangGraph + LiteLLM |
| LLM | BYOK：草稿 DeepSeek / 精修 Qwen / 评估 Claude（可自选） |
| 数据库 | PostgreSQL 16 + pgvector + Redis |
| 前端 | Next.js 14 + TailwindCSS + Tiptap |
| 依赖 | Python 用 uv（`backend/pyproject.toml`），Node 用 npm |

## 快速开始

前置：Docker Desktop（WSL2 后端）。

```powershell
# 0. 生成自签 TLS 证书（nginx 启动必需；仅本机 https://localhost 用，正式域名走 certbot，见 deploy/README.md）
mkdir deploy/nginx/certs
# openssl 不在 PATH？Windows 一般没有——Git for Windows 自带，与 git 同目录：
$openssl = Join-Path (Split-Path (Get-Command git).Source -Parent) "openssl.exe"
& $openssl req -x509 -nodes -newkey rsa:2048 `
  -keyout deploy/nginx/certs/privkey.pem `
  -out deploy/nginx/certs/fullchain.pem -days 365 -subj "/CN=localhost"

# 1. 容器密钥（根目录，强密码，.env.example 已预生成直接可用）
Copy-Item .env.example .env

# 2. API Key（后端）
cd backend && Copy-Item .env.example .env   # 填 DEEPSEEK_API_KEY / DASHSCOPE_API_KEY 等

# 3. 构建启动全栈（nginx + PG + Redis + backend + frontend）
docker compose up -d --build

# 4. 初始化数据库
docker compose exec backend alembic upgrade head
docker compose exec backend python scripts/check_migrations.py
```

访问 **https://localhost** → 点击 ⚙ 配置 API Key → 开始写作。
健康检查：`curl -k https://localhost/v1/health` → `{"status":"ok"}`

> 本地进程热重载（改代码免 rebuild）：`uv run uvicorn app.main:app --reload --port 8000` + `npm run dev`，DB 仍用 compose 栈。

### 从零彻底重建（清容器 + 数据 + 镜像）

```powershell
docker compose down -v        # 停容器 + 删数据卷
docker compose rm -f          # 删容器（保险）
docker image prune -a         # 删本地镜像（重建会重新拉基础镜像）
# 然后重跑上面「快速开始」步骤 0-4 即可
```

> `deploy/nginx/certs/` 不入库（gitignore）；丢了就重跑步骤 0。`pg_data`/`redis_data` 是数据卷，`down` 保留、`down -v` 清除（清后需重新迁移）。

## 常用命令

```powershell
docker compose up -d          # 启动全栈
docker compose down           # 停止（保留数据卷）
docker compose down -v        # 停止并清卷（需重新迁移）
docker compose logs -f backend
docker compose exec backend alembic upgrade head   # 更新后补迁移
```

## 核心特性

- **task_type 路由**：按任务走最少 pipeline 阶段（续写 ~2s 出首字，不走评估循环）
- **真流式输出**：逐 token 经 SSE 实时推送，前端逐字渲染
- **阶段级降级**：单阶段失败跳过并标注，pipeline 继续
- **BYOK**：三段各配独立 provider，快速预设 + 连接测试
- **RAG 记忆检索**：章节/角色/世界观/剧情四集合 pgvector 检索，小说设定优先
- **多 Agent 系统**：大纲角色 / 章节编辑 / 评估矩阵 / 安全审核
- **作品导出**：md / txt / epub（零新依赖）
- **写作工具**：生成总纲 / 续写 / 扩写 / 重写 / 降AI / 编剧对话 / 知识库 / 统计看板

## 目录结构

```
backend/                # FastAPI + LangGraph
  app/                  # 核心代码
    agents/             # 角色化 Agent
    api/                # REST 端点
    pipeline/           # 三阶段流水线（核心）
    planner/            # DAG 编排器
    eval/               # 评估矩阵
    safety/             # 内容安全
    services/           # 业务逻辑
  alembic/              # 数据库迁移
  scripts/              # 工具脚本（check_migrations 等）
  tests/
  pyproject.toml        # uv 依赖声明（唯一权威）
frontend/               # Next.js 14
  src/app/              # 页面路由
  src/components/       # UI 组件
deploy/                 # 服务器部署（nginx 等）
docker-compose.yml      # 全栈 compose
docker-compose.local.yml  # 已废弃（仅旧版本地 DB），勿用
```

## 架构

**整体拓扑**：`浏览器 → nginx(80/443, TLS+CSP) → FastAPI 后端 → [LangGraph 流水线 → litellm → BYOK LLM] + [PostgreSQL/pgvector + Redis]`

```mermaid
flowchart LR
    U[浏览器<br/>Next.js 前端] -->|https /v1/chat SSE| NG[nginx :80/443]
    NG --> BA[FastAPI 后端]
    BA --> PS[stream_pipeline]
    PS --> PL[LangGraph 流水线]
    PL --> LLM[LLM 供应商<br/>BYOK DeepSeek/Qwen/Claude]
    BA --> SRV[业务服务层]
    SRV --> DB[(PostgreSQL 16 + pgvector)]
    SRV --> RD[(Redis)]
```

**Pipeline 路由**（按 `task_type` 取最少阶段链，评估不过最多循环 5 次）：

```mermaid
flowchart TD
    START([START]) --> RET[retrieval RAG]
    RET --> DRAFT[draft 注入检索上下文]
    DRAFT --> REF[refine]
    REF --> EVAL[evaluate 评分]
    EVAL -->|分数低且迭代<5| REF
    EVAL -->|通过| SAFE[safety_check]
    SAFE --> ENDE([END])
    C[continue/outline] -.-> RET
    R[rewrite/polish] -.-> REF
    style EVAL stroke:#8a5a2b,stroke-width:2px
```

**阶段链**：`generate` 全链 + 循环 ｜ `continue`/`outline` retrieval→draft→safety ｜ `rewrite`/`polish` refine→safety。

**BYOK**：前端 `X-Provider-Config` 头上传分段凭证，后端 SSRF 校验 api_base（`APIBaseNotAllowed`），日志脱敏（`_redact_key`）。
**RAG**：retrieval_node 在 draft 前对 4 集合（章节/角色/世界观/事件）pgvector 语义检索，注入 draft/refine 提示词；失败降级不阻断。
**数据**：PostgreSQL 16 + pgvector（Alembic 迁移，`check_migrations.py` 前置校验）；Redis 缓存/限流。

> 完整交互式版本：`docs/diagrams/architecture.html`

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/chat` | 流式聊天（SSE，含 task_type 路由） |
| POST | `/v1/chat/test` | 连接测试 |
| GET | `/v1/health` | 健康检查 |
| CRUD | `/v1/documents/...` / `chapters/` / `characters/` / `world-settings/` / `plot-events/` | 作品内容管理 |
| POST | `/v1/documents/{id}/retrieve` | RAG 语义检索 |
| GET | `/v1/documents/{id}/export?format=md|txt|epub` | 作品导出 |
| GET | `/v1/stats/dashboard` | 写作统计 |
| CRUD | `/v1/documents/{id}/knowledge-docs` | 知识库 |

> 除 `/v1/health` 外受保护端点均需 `X-API-Key`（`API_KEYS` 白名单，见 `.env.example`）。`API_KEYS` 未配置时返回 503 引导文案。

## 验证清单

| 项 | 期望 |
|---|---|
| `docker compose ps` | 5 容器 running，postgres/redis healthy |
| `curl -k https://localhost/v1/health` | `{"status":"ok"}` |
| 浏览器 https://localhost | 编辑器界面 |
| 配置 BYOK → 测试连接 | ✅ 连接成功 |
| 点击"续写" | ~1-2s 后文字逐字出现 |

## 常见问题

- **拉取镜像慢/失败**：配置 Docker 镜像加速器（Docker Desktop → Settings → Docker Engine 加 `registry-mirrors`，如 `docker.xuanyuan.me` / `docker.1ms.run`）。
- **Redis 连接失败**：`docker compose ps` 确认容器 running，否则 `docker compose up -d`。
- **迁移双头**：用 `check_migrations.py` / `alembic heads` 核对，分叉先合并链再升级。
- **`litellm` 升级失败**：`litellm==1.90.7`（<1.91 硬约束，1.91+ 引入 Rust 组件）。
- **重建虚拟环境**：`cd backend && rm -r .venv && uv sync --locked`。

## 开发约定

- **提交**：Conventional Commits（`feat:` / `fix:` / `docs:` / `chore:` 等）
- **测试**：新增功能必带测试，覆盖率 ≥ 80%
- **依赖**：不换框架；LiteLLM 是唯一 LLM 入口且 `==` 精确 pin；Python 依赖用 uv，版本以 `backend/uv.lock` 为准
- **AI 协作**：[AGENTS.md](AGENTS.md)