# API 接口审查报告

> 审查人：kilo（接口/兼容性）
> 日期：2026-08-16
> 范围：`backend/app/api/` + `backend/app/schemas/`

---

## 1. 认证逻辑统一

**问题：** `_require_api_key` 在 3 处独立定义，逻辑完全相同但未统一引用。

| 文件 | 函数名 | 行号 | 是否从 `_deps` 导入 |
|------|--------|------|-------------------|
| `_deps.py` | `require_api_key` | 16-25 | N/A（定义处） |
| `documents.py` | `_require_api_key` | 44-58 | ❌ 本地重复定义 |
| `chapters.py` | `_require_api_key` | 67-75 | ❌ 本地重复定义 |
| `characters.py` | `require_api_key` | 21 | ✅ 从 `_deps` 导入 |
| `world_settings.py` | `require_api_key` | 20 | ✅ 从 `_deps` 导入 |
| `plot_events.py` | `require_api_key` | 21 | ✅ 从 `_deps` 导入 |
| `retrieval.py` | `require_api_key` | 14 | ✅ 从 `_deps` 导入 |

**附加重复：** `extract_embedding_stage` 在 `chapters.py`（47-64行）也有本地重复定义，与 `_deps.py`（36-59行）逻辑完全相同。

**建议：**
- `documents.py` 删除本地 `_require_api_key`，改为 `from app.api._deps import require_api_key`
- `chapters.py` 删除本地 `_require_api_key` 和 `_extract_embedding_stage`，改为从 `_deps` 导入
- `chapters.py` 的 `_load_parent` 也应改用 `_deps.load_parent`

---

## 2. 错误响应规范

**问题：** 三种不同的错误响应格式并存，缺乏统一模型。

| 端点类型 | 错误格式 | 示例 |
|----------|----------|------|
| REST 端点 | HTTP 状态码 + JSON `detail` | `{"detail":"作品不存在"}` (404) |
| SSE `/v1/chat` | `{"type":"error","detail":"..."}` | 通过 `_encode_error()` 发送 |
| `/v1/chat/test` | HTTP 状态码 + JSON `detail` | `401` / `{"detail":"..."}` |

**已统一：**
- 所有 REST 端点 404/401/400 错误消息已中文化
- SSE 错误事件字段 `errorText` → `detail`，与 REST 对齐
- `/v1/chat/test` 错误分支改为 HTTPException（401/400/502/404/500）

**统一错误模型：** `schemas/error.py` `ErrorResponse(detail, code)`

---

## 修复状态

- 认证统一：✅ 已修复（`documents.py` / `chapters.py` 改为从 `_deps.py` 导入共享依赖）
- 错误响应中文化：✅ 已修复（`documents.py` / `chapters.py` / `characters.py` / `plot_events.py` / `world_settings.py` / `_deps.py` / `retrieval.py` 404/401/400 消息统一为中文）
- 版本策略 `/health` → `/v1/health`：✅ 已修复（API + tests + README + nginx 配置同步更新）
- 统一错误响应模型：✅ 已修复（`schemas/error.py` ErrorResponse；SSE `errorText` → `detail`；`/v1/chat/test` 错误分支改为 HTTPException）

**现状：** 所有功能端点已统一使用 `/v1/` 前缀（含 `/v1/health`）。

| 路径 | 是否有版本前缀 |
|------|---------------|
| `/v1/chat` | ✅ |
| `/v1/chat/test` | ✅ |
| `/v1/health` | ✅ |
| `/v1/documents` | ✅ |
| `/v1/documents/{id}/chapters` | ✅ |
| `/v1/documents/{id}/characters` | ✅ |
| `/v1/documents/{id}/world-settings` | ✅ |
| `/v1/documents/{id}/plot-events` | ✅ |
| `/v1/documents/{id}/retrieve` | ✅ |

**缺失项：**
- 无版本演进文档
- 无弃用策略（Deprecation header）
- 无版本协商机制

**建议：**
- 建立版本管理规范（可在 `.orca/` 或 `docs/` 中），明确：
  - 当前版本 v1 的承诺支持周期
  - 新版本 v2 的迁移路径
  - 弃用端点需提前 N 个版本设置 `Deprecation: true` header

---

## 4. 端点清单

共 30 个端点。

### 聊天
| 方法 | 路径 | 认证 | 请求模型 | 响应模型 |
|------|------|------|----------|----------|
| POST | /v1/chat | X-Provider-Config | ChatRequest | SSE 流 |
| POST | /v1/chat/test | X-Provider-Config | query: stage | dict |

### 健康检查
| 方法 | 路径 | 认证 | 请求模型 | 响应模型 |
|------|------|------|----------|----------|
| GET | /health | 无 | - | dict |

### 文档（作品）
| 方法 | 路径 | 认证 | 请求模型 | 响应模型 |
|------|------|------|----------|----------|
| GET | /v1/documents | X-API-Key | Query params | DocumentListResponse |
| POST | /v1/documents | X-API-Key | DocumentCreate | DocumentRead (201) |
| GET | /v1/documents/{id} | X-API-Key | - | DocumentRead |
| PATCH | /v1/documents/{id} | X-API-Key | DocumentUpdate | DocumentRead |
| DELETE | /v1/documents/{id} | X-API-Key | - | 204 |
| POST | /v1/documents/{id}/restore | X-API-Key | - | DocumentRead |
| DELETE | /v1/documents/{id}/permanent | X-API-Key | - | 204 |

### 章节
| 方法 | 路径 | 认证 | 请求模型 | 响应模型 |
|------|------|------|----------|----------|
| GET | /v1/documents/{id}/chapters | X-API-Key | Query | ChapterListResponse |
| POST | /v1/documents/{id}/chapters | X-API-Key | ChapterCreate | ChapterRead (201) |
| PATCH | /v1/documents/{id}/chapters/{id} | X-API-Key | ChapterUpdate | ChapterRead |
| DELETE | /v1/documents/{id}/chapters/{id} | X-API-Key | - | 204 |
| PUT | /v1/documents/{id}/chapters/reorder | X-API-Key | ChapterReorderRequest | ChapterListResponse |

### 角色
| 方法 | 路径 | 认证 | 请求模型 | 响应模型 |
|------|------|------|----------|----------|
| GET | /v1/documents/{id}/characters | X-API-Key | Query | CharacterListResponse |
| POST | /v1/documents/{id}/characters | X-API-Key | CharacterCreate | CharacterRead (201) |
| GET | /v1/documents/{id}/characters/{id} | X-API-Key | - | CharacterRead |
| PATCH | /v1/documents/{id}/characters/{id} | X-API-Key | CharacterUpdate | CharacterRead |
| DELETE | /v1/documents/{id}/characters/{id} | X-API-Key | - | 204 |

### 世界设定
| 方法 | 路径 | 认证 | 请求模型 | 响应模型 |
|------|------|------|----------|----------|
| GET | /v1/documents/{id}/world-settings | X-API-Key | Query | WorldSettingListResponse |
| POST | /v1/documents/{id}/world-settings | X-API-Key | WorldSettingCreate | WorldSettingRead (201) |
| GET | /v1/documents/{id}/world-settings/{id} | X-API-Key | - | WorldSettingRead |
| PATCH | /v1/documents/{id}/world-settings/{id} | X-API-Key | WorldSettingUpdate | WorldSettingRead |
| DELETE | /v1/documents/{id}/world-settings/{id} | X-API-Key | - | 204 |

### 情节事件
| 方法 | 路径 | 认证 | 请求模型 | 响应模型 |
|------|------|------|----------|----------|
| GET | /v1/documents/{id}/plot-events | X-API-Key | Query | PlotEventListResponse |
| POST | /v1/documents/{id}/plot-events | X-API-Key | PlotEventCreate | PlotEventRead (201) |
| GET | /v1/documents/{id}/plot-events/{id} | X-API-Key | - | PlotEventRead |
| PATCH | /v1/documents/{id}/plot-events/{id} | X-API-Key | PlotEventUpdate | PlotEventRead |
| DELETE | /v1/documents/{id}/plot-events/{id} | X-API-Key | - | 204 |

### 检索
| 方法 | 路径 | 认证 | 请求模型 | 响应模型 |
|------|------|------|----------|----------|
| POST | /v1/documents/{id}/retrieve | X-API-Key | RetrievalRequest | RetrievalResponse |
