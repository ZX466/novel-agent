# 多轮对话助手接口设计

> 任务：F1 对话助手协议
> 状态：待 Claude 评审
> 日期：2026-08-17

---

## 1. 背景与目标

当前 `/v1/chat` 已支持多轮对话 + task_type 路由（outline/generate/continue/rewrite/polish）。
本次新增「对话助手」模式：在用户多轮对话中，自动注入章节/大纲上下文，让模型具备作品级连续记忆能力。

---

## 2. 方案评估

### 方案 A：复用 `/v1/chat` 扩展

**做法：**
- 在 `ChatRequest` 新增可选字段：
  - `context_doc_id: int | None`
  - `context_chapter_ids: list[int] | None`
  - `context_mode: "outline" | "selected" | "full" | None`
- 新增 `task_type="assistant"`，后端在 `_event_stream` 前组装上下文 prompt
- 复用现有 SSE 流式输出 + BYOK + 错误处理

**优点：**
- 零额外路由，前端无需改 base URL
- BYOK / 流式 / 限流完全复用现有基础设施
- 客户端（Web/Mobile）只需多传 3 个可选字段

**缺点：**
- `ChatRequest` Schema 逐渐膨胀
- assistant 模式的验证逻辑与普通 chat 耦合

### 方案 B：独立端点 `/v1/assistant`

**做法：**
- 新端点 `POST /v1/assistant`，独立 Request/Response Schema
- 内部仍调用 `stream_pipeline`，但上下文组装在 endpoint 层完成
- 可独立演化（如后续加 function calling、多工具编排）

**优点：**
- Schema 解耦，assistant 可引入工具调用、多步推理等
- 不影响现有 `/v1/chat` 契约

**缺点：**
- 前端需维护两个聊天 URL
- BYOK / 流式基础设施需重复声明

---

## 3. 推荐方案：方案 A（复用 `/v1/chat`）

理由：
1. 当前项目阶段只需「上下文注入」，无需独立工具调用栈
2. 前端改动最小（SettingsDialog / useChat 已支持 `/v1/chat`）
3. 保持单一入口便于监控和限流

> **备选：** 若后续需要 function calling / 多工具编排，再拆分为 `/v1/assistant`。

---

## 4. 接口定义

### 4.1 Request（扩展 ChatRequest）

```python
class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., max_length=100)
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool | None = None
    task_type: str | None = None  # "assistant" | "generate" | "continue" | ...

    # 对话助手上下文（仅 task_type=assistant 时生效）
    context_doc_id: int | None = None
    context_chapter_ids: list[int] | None = None
    context_mode: Literal["outline", "selected", "full"] | None = None
```

### 4.2 上下文组装逻辑

当 `task_type="assistant"` 时，后端按 `context_mode` 从数据库拉取上下文，拼接到 system prompt：

| mode | 数据来源 | 注入内容 |
|------|----------|----------|
| `outline` | `documents.metadata_json.outline` | 大纲文本 |
| `selected` | `chapters` WHERE id IN context_chapter_ids | 指定章节正文 |
| `full` | `chapters` WHERE novel_id = context_doc_id | 全文（按需截断） |

组装后的 messages 结构：
```
[system] 你是一位小说创作助手。以下是当前作品上下文：
  - 大纲：...
  - 章节1：...
  - 章节2：...
[user] 用户消息...
```

### 4.3 Response

复用现有 SSE 流式响应（AI SDK v5 UI Message Stream），无变化。

---

## 5. 与现有路由的关系

| 端点 | 说明 |
|------|------|
| `POST /v1/chat` | 通用聊天 + 创作流水线 + assistant 上下文注入 |
| `POST /v1/chat/test` | 连接测试，不变 |
| `POST /v1/chat/assistant` | **不新增**，避免路由膨胀 |

---

## 6. 待 Claude 评审项

1. `context_mode="full"` 是否需要对长文做截断（如按 token 数限制）？
2. 上下文注入位置：system prompt vs 最后一轮 user message？
3. 是否需要暴露 `context_max_tokens` 参数控制注入长度？
4. assistant 模式是否需要对 `messages` 做去重/压缩（防止上下文窗口溢出）？
