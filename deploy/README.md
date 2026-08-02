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

# 6. 验证
curl http://localhost/health   # 应返回 {"status":"ok"}
```

## HTTPS（可选）

把证书放到 `deploy/nginx/certs/` 下，在 `app.conf` 加 443 server block + `ssl_certificate`，并在 `docker-compose.yml` 的 nginx volumes 挂载证书目录。

## 常见问题

- **前端发消息没流式效果**：检查 nginx 的 `/v1/chat` location 是否有 `proxy_buffering off`。
- **连接测试失败**：确认 nginx 代理了 `/v1/chat/test` 端点（与 `/v1/chat` 相同的 location 即可）。
- **CORS 报错**：检查 backend `.env` 的 `CORS_ORIGINS` 是否包含前端实际访问的 origin。
- **Alembic 报错找不到 extension**：先 `CREATE EXTENSION vector;` 再 `alembic upgrade head`。
- **评估超时**：每个评估维度有 30 秒超时。如需调整，修改 `backend/app/eval/matrix.py` 中的 `_EVAL_DIM_TIMEOUT`。
