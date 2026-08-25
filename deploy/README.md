# 服务器部署（腾讯云）

> **本地开发不要看这个文档。** 本地用 `backend/` 和 `frontend/` 各自的 README 启动方式（`uvicorn` + `next dev`）。
> 这里只讲腾讯云服务器上的 Docker Compose 部署。

## 前置条件

1. 腾讯云服务器已装好 Docker + Docker Compose v2
2. 服务器安全组放行 80/443 端口
3. 已有 DeepSeek / DashScope / 中转 Claude 的 API key
4. （可选）有自己的域名 + SSL 证书

## 步骤

```bash
# 1. 在服务器上 clone 或 scp 整个项目
scp -r ./project11 user@<server-ip>:/opt/project11
ssh user@<server-ip>
cd /opt/project11

# 2. 复制环境变量模板并填入真实值
cp .env.example .env
vi .env   # 填 DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / RELAY_API_KEY / RELAY_API_BASE 等
cp backend/.env.example backend/.env
vi backend/.env   # 同步填入（compose 用这个）

# 3. 构建并启动
docker compose up -d --build

# 4. 看日志
docker compose logs -f backend
docker compose logs -f nginx

# 5. 跑数据库迁移（容器内 PG 启动后）
docker compose exec postgres psql -U postgres -d project11 -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker compose exec backend alembic upgrade head

# 6. 迁移链校验（R7-3 生产就绪）：必须只显示一个 head，且为最新迁移
docker compose exec backend alembic heads   # 必须只有一行输出：c0d1e2f3a4b50 (head)
# ⚠️ 若输出两个 head（如 1a2b3c4d5e6f 与 f6a7b8c9d0e1 并存），说明存在分叉迁移，
#    生产升级会因 "Multiple head revisions" 失败——这是 P0，须先合并迁移链再继续。

# 7. 数据回填（R7-3 生产就绪）：为已有 documents/novels 写入 owner_key_hash
#    （幂等，可重复执行；仅更新 owner_key_hash 为空的存量行，不覆盖已回填数据）
docker compose exec backend python -m scripts.backfill_owner_key_hash

# 7.1 回填验证（非阻塞，退出码 0 即正常）
docker compose exec backend alembic heads   # 仍应单头

# 8. 验证
curl http://localhost/v1/health   # 应返回 {"status":"ok"}
```

## 生产环境变量

> 以下为生产部署必需的全部环境变量。**所有密钥仅存在于服务器 `.env` / `backend/.env`，不入库、不提交 git。**

| 变量 | 必填 | 说明 |
|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://...` 异步连接串（含密码） |
| `REDIS_URL` | ✅ | `redis://:<密码>@host:16379/0` |
| `API_KEYS` | ✅ | JSON 数组，受保护端点白名单，如 `'["key-a","key-b"]'` |
| `DEEPSEEK_API_KEY` | 二选一 | DeepSeek 供应商 KEY |
| `DASHSCOPE_API_KEY` | 二选一 | DashScope 供应商 KEY |
| `RELAY_API_KEY` | 可选 | 中转供应商 KEY |
| `RELAY_API_BASE` | 可选 | 中转供应商地址 |
| `CORS_ORIGINS` | 生产必填 | JSON 数组，含真实前端域名 |
| `APP_ENV` | 建议 | `production` |
| `SECRET_KEY` / `JWT_SECRET` | 生产必填 | 会话/签名密钥，≥32 字符随机 |
| `CORS_ORIGINS` | 生产必填 | JSON 数组，含真实前端域名（见上方步骤） |

> **R6-3 交稿雷达（安全预检）为内置规则集**，无需环境变量开关。
> `SAFETY_ENABLED` / `SAFETY_RULES` **不属于现有配置**（config.py 无此字段），请勿在 `.env` 中填写。如需调整规则，修改代码 `backend/app/safety/` 下的规则集。

## HTTPS（必须，R8-6）

> 反向代理**默认强制 HTTPS**：`app.conf` 对 80 端口直接 301 → 443，无 TLS 时 nginx 以 `listen 443 ssl` 态启动会失败。所有 `X-API-Key` / `X-Provider-Config` 头经公网传输，**必须走 TLS，不允许明文 HTTP 回退**（安全审计 H2）。

1. 准备证书，放入 `deploy/nginx/certs/`（compose 已挂载到容器 `/etc/nginx/certs`）：
   - **正式域名**：用 Let's Encrypt 签 `fullchain.pem` + `privkey.pem`（如 `certbot --nginx -d your.domain` 或容器化签发后拷入）。
   - **无域名/测试**：自签亦可——
     ```bash
     mkdir -p deploy/nginx/certs
     openssl req -x509 -nodes -newkey rsa:2048 \
       -keyout deploy/nginx/certs/privkey.pem \
       -out deploy/nginx/certs/fullchain.pem -days 365 -subj "/CN=your-server-ip"
     ```
2. nginx 已做 80→443 跳转 + HSTS/Security 头（XFO/Content-Type/Referrer）。443 映射（`443:443`）此前是死端口，现已对齐监听。
3. **CSP 未强制**：Next.js App Router 内联 RSC 引导脚本，直接加 CSP 会打爆渲染。需用 Next.js middleware nonce 策略后再配（R8 后续项，已在代码注释标注）。

> 本地开发不跑 compose，不受影响。

## 常见问题

- **前端发消息没流式效果**：检查 nginx 的 `/v1/chat` location 是否有 `proxy_buffering off`。
- **连接测试失败**：确认 nginx 代理了 `/v1/chat/test` 端点（与 `/v1/chat` 相同的 location 即可）。
- **CORS 报错**：检查 backend `.env` 的 `CORS_ORIGINS` 是否包含前端实际访问的 origin。
- **Alembic 报错找不到 extension**：先 `CREATE EXTENSION vector;` 再 `alembic upgrade head`。
- **评估超时**：每个评估维度有 30 秒超时。如需调整，修改 `backend/app/eval/matrix.py` 中的 `_EVAL_DIM_TIMEOUT`。
