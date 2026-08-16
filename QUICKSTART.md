# Quickstart — 5 分钟跑起来

> 极简上手路径。完整文档见 [README.md](README.md)，部署见 [deploy/README.md](deploy/README.md)。

## 前置条件

- Python 3.11+、Node 18+、[uv](https://docs.astral.sh/uv/)
- PostgreSQL 16（含 pgvector 扩展）+ Redis（部署在腾讯云服务器，本地走 SSH 隧道）

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
- **本机不要跑 `docker compose`**：Docker 仅部署在腾讯云服务器，本地用 uvicorn + next dev 直跑。
- **流式不实时**：确认走的是 SSE 且后端使用 `on_token` 回调（详见 README §4.1）。
