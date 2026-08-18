# 卡片 05｜换模型供应商

> 目标：在多个 LLM 供应商之间切换 / 测试连接，找到可用的组合。

## 操作步骤

1. **打开设置**
   - 前端 → “设置”，BYOK 配置区。

2. **填写新供应商**
   - API Base（如 Azure OpenAI、DeepSeek、本地 relay 等 OpenAI 兼容端点）、API Key、模型名。
   - 分 stage（draft / refine / embedding）配置；不同 stage 可指向不同供应商。

3. **测试连接**
   - 点击“测试连接”（`POST /v1/chat/test?stage=...`），后端校验：
     - `api_base` 协议必须是 http/https，且非内网地址（SSRF 防护）；
     - 连接失败返回通用错误（不泄漏密钥/URL 细节）。
   - 若模型名不符，可能自动回退到 `/embeddings` 探测（仅针对“does not exist”类错误）。

4. **保存生效**
   - 配置保存在前端本地（`X-Provider-Config` 随请求发送），无后端持久化负担。

## 一行验证

> “测试连接”返回成功，且“续写”正常流式输出。

## 常见坑

- **“API Base URL 不被允许”**：地址为内网/环回/链路本地，或非 http(s)；需在 `BYOK_ALLOW_LOCAL_API_BASE=true` 时才允许 localhost 的 BYOK。
- **限流 429**：连接测试配额更严（`chat_test_rate_limit_per_minute=3`）；快速连点会触发 `Retry-After`，稍后再试。
- **模型不存在**：draft 与 embedding 常需要不同模型；在对应 stage 配置正确的模型名。