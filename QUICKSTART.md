# Quickstart — 5 分钟跑起来

> 极简上手路径。完整文档见 [README.md](README.md)，部署见 [deploy/README.md](deploy/README.md)。

## 前置条件

- Python 3.11+、Node 18+、[uv](https://docs.astral.sh/uv/)
- PostgreSQL 16（含 pgvector 扩展）+ Redis（部署在腾讯云服务器，本地走 SSH 隧道）

## 0. 数据库准备（二选一）

### 方式 A：SSH 隧道直连腾讯云（推荐，依赖服务器在线）

```powershell
ssh -N -L 5432:localhost:5432 -L 16379:localhost:16379 user@<服务器IP>
```

### 方式 B：本地 Docker 起 PG + Redis（服务器到期/离线时）

只用 `docker-compose.local.yml`，**仅包含 PG + Redis 两个容器**，前后端仍用本地进程（uvicorn + next dev）。该文件维护在 main 分支，从工作树或克隆仓库根目录取：

```powershell
cd 项目根目录
Copy-Item .env.example .env         # 首用：创建容器密钥（强密码，.env 不入库）
docker compose -f docker-compose.local.yml up -d        # 起容器
docker compose -f docker-compose.local.yml ps           # 确认 healthy
docker compose -f docker-compose.local.yml down         # 停止（数据保存在卷中）
```

> 容器密码**必须**来自根目录 `.env`（`POSTGRES_PASSWORD` / `REDIS_PASSWORD`，≥20 字符），缺失时 compose 直接失败；端口仅绑定 127.0.0.1。

后端 `.env` 用与根目录 `.env` 相同的密码指向本机即可：

```ini
DATABASE_URL=postgresql+asyncpg://postgres:<POSTGRES_PASSWORD>@localhost:5432/project11
REDIS_URL=redis://:<REDIS_PASSWORD>@localhost:16379/0
```

> 生产/默认方式是方式 A。方式 B 是腾讯云到期或断网时的本地兜底，保证开发不中断。

## 1. 开 SSH 隧道（连接云端 DB/Redis）

```powershell
ssh -N -L 5432:localhost:5432 -L 16379:localhost:16379 user@<服务器IP>
```

## 2. 启动后端

```powershell
cd backend
Copy-Item .env.example .env        # 编辑 .env 填入 DB/Redis/API keys
uv venv .venv --python 3.11
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

> 首次需在 PostgreSQL 中建库并启用扩展：
> `CREATE DATABASE project11; \c project11; CREATE EXTENSION IF NOT EXISTS vector;`

## 3. 启动前端（新开一个终端）

```powershell
cd frontend
echo NEXT_PUBLIC_BACKEND_URL=http://localhost:8000 > .env.local
npm install
npm run dev
```

## 4. 验证

| 检查 | 期望 |
|---|---|
| `curl http://localhost:8000/v1/health` | `{"status":"ok"}` |
| 打开 http://localhost:7421 | 小说编辑器界面 |
| 配置 BYOK → 测试连接 | ✅ 连接成功 |
| 点击"续写" | ~1-2 秒后文字逐字出现 |

## 常见坑

- **`litellm` 安装失败**：requirements.txt 已 pin `litellm<1.91`（1.91+ 引入 Rust 组件），不要手动升级。
- **CORS 报错**：检查 `backend/.env` 的 `CORS_ORIGINS` 是否含 `http://localhost:7421`。
- **本机 Docker 只用于"数据库容器"**：`docker-compose.local.yml`（本地 PG+Redis）可跑；不要跑 `docker-compose.yml`（那是腾讯云服务器全栈部署专用）。
- **流式不实时**：确认走的是 SSE 且后端使用 `on_token` 回调（详见 README §4.1）。
