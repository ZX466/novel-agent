# Quickstart — 5 分钟跑起来

> 极简上手路径。完整文档见 [README.md](README.md)，部署见 [deploy/README.md](deploy/README.md)。

> **👨‍💻 开始创作？按意图选卡直达** → [创作配方卡索引](docs/recipes/index.md)：01 新书三步开写 / 02 续写旧稿 / 03 喂知识库 / 04 导出投稿 / 05 换模型供应商

## 前置条件

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)（WSL2 后端；首次拉镜像较慢可配置镜像加速器）
- 有任一 LLM 的 API Key（DeepSeek / DashScope / 中转 Claude 等）
- （可选）[uv](https://docs.astral.sh/uv/)、Node 18+ — 仅本地进程开发模式需要

## 1. 一键启动全栈（5 个容器）

```powershell
cd 项目根目录
Copy-Item .env.example .env          # 首用：创建容器密钥（POSTGRES_PASSWORD / REDIS_PASSWORD，强密码不入库）
docker compose up -d --build         # 构建并启动 nginx + PG + Redis + backend + frontend
docker compose ps                    # 确认 postgres / redis healthy，其余 up
```

> 端口仅 nginx 暴露 80/443，其余服务对宿主隐藏；数据保存在 Docker 卷 `pg_data` / `redis_data`，删容器不丢。

## 2. 配置 API Key

```powershell
cd backend
Copy-Item .env.example .env          # 填入真实 API Key（DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / RELAY_*）
# DATABASE_URL / REDIS_URL 容器内由 compose 自动指向内部服务，无需手工改
```
然后重启后端容器使环境变量生效：
```powershell
cd 项目根目录
docker compose restart backend
```

## 3. 初始化数据库（首次/代码更新后）

```powershell
docker compose exec backend alembic upgrade head
docker compose exec backend python scripts/check_migrations.py   # 单头 + 无未应用（失败退出非 0）
```

## 4. 访问

浏览器打开 **https://localhost:8443** → 点击 ⚙ 配置 API Key → 开始写作。

## 5. 验证

| 检查 | 期望 |
|---|---|
| `curl -k https://localhost:8443/v1/health` | `{"status":"ok"}` |
| 打开 https://localhost:8443 | 小说编辑器界面 |
| 配置 BYOK → 测试连接 | ✅ 连接成功 |
| 点击"续写" | ~1-2 秒后文字逐字出现 |

## 6. 功能速览

> 以下核心功能由历史轮次交付，端点见 [README §六 表格](README.md)。

- **作品导出**：作品页点"导出"（`md / txt / epub`，EPUB 为标准库 zip 生成，零依赖）。
- **本地知识库**：作品页上传参考资料，自动分块 + 向量化；RAG 检索自动合并（**小说设定优先**）。可上传 / 列表 / 删除。
- **写作统计**：统计看板显示近 30 天字数曲线、连续写作天数、今日目标达成情况。
- **AI 编剧对话**：对话界面多轮问答，自动带章节/大纲上下文，结果可一键插入正文。
- **交稿雷达**：导出前隐私/版权/敏感表达安全预检（SafetyScanDialog）。

> 受保护端点鉴权默认**开放模式**：未配置 `API_KEYS` 时直接放行，前端填 AI 供应商 Key 即可使用（无需网站 Key）。配置 `API_KEYS` 后需携带 `X-API-Key`。

## 常见坑

- **`alembic upgrade head` 报 "Multiple head revisions"**：迁移链分叉。用 `check_migrations.py` / `alembic heads` 核对，保持单一 head；分叉先合并链再升级。
- **`litellm` 安装失败**：`pyproject.toml` 已 pin `litellm==1.90.7`（<1.91 硬约束），1.91+ 引入 Rust 组件，不要手动升级。
- **CORS 报错**：检查 `backend/.env` 的 `CORS_ORIGINS` 是否含 `https://localhost:8443`（容器内 compose 已覆盖默认，本地进程模式需自行加）。
- **导出/统计/知识库 401**：仅在配置了 `API_KEYS` 时出现——确认请求携带 `X-API-Key`（前端设置弹窗「网站鉴权 Key」填白名单中任一值）；未配置 `API_KEYS` 时默认开放不拦。
- **镜像拉取失败**：国内网络配置 Docker 镜像加速器（Docker Desktop → Settings → Docker Engine 加 `registry-mirrors`，见 README §八 FAQ）。