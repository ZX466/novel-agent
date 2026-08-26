# Agent Registry — 能力域注册表

> **重要：每个能力域只指定一个推荐 Agent，不重复分配。**
> **未覆盖的能力域保持空白，后续按需补充（由用户决定，不要随意更改）。**

---

## 注册表

| 能力域 | 推荐 Agent | 评审 Agent | 状态 |
|--------|-----------|-----------|------|
| 架构 | Claude | Codex | ✅ 已分配 |
| 代码质量 | Claude | Codex | ✅ 已分配 |
| 逻辑 | Claude | Codex | ✅ 已分配 |
| 测试 | Claude | Codex | ✅ 已分配 |
| 依赖 | cline | Claude | ✅ 已分配 |
| 配置 | cline | Claude | ✅ 已分配 |
| 文档 | cline | Claude | ✅ 已分配 |
| 安全 | Codex | cline | ✅ 已分配 |
| 合规 | Codex | cline | ✅ 已分配 |
| 风险 | Codex | cline | ✅ 已分配 |
| 性能 | Pi | cline | ✅ 已分配 |
| 数据 | opencode | Codex | ✅ 已分配 |
| 数据库 | opencode | Codex | ✅ 已分配 |
| 接口 | kilo | Claude | ✅ 已分配 |
| 兼容性 | kilo | Claude | ✅ 已分配 |
| 前端 | Claude | Codex | ✅ 已分配 |
| 体验 | Claude | Codex | ✅ 已分配 |
| 发布 | Claude | Codex | ✅ 已分配 |
| 运维 | Claude | Codex | ✅ 已分配 |

---

## Agent 工作树映射（2026-08-19 起：已收敛）

> **分支与工作树已全部收敛**：仅保留 `main` 分支（本地 + gitee + github）。原 5 个 `ZX466/*` 分支与工作树已删除（工作树物理目录待关闭会话后清理）。
> 各 Agent 的记忆已存档于主工作树：`.orca/agent-memory-pi.md`、`.orca/agent-memory-codex.md`、`AGENTS.md`（opencode 会话记忆）。
> 后续协作直接在 `main` 上按能力域分工，通过主工作树 `.orca/talking.txt` 留言流转。

| Agent | 能力域 | 协作位置 | 评审 Agent |
|-------|--------|---------|-----------|
| Claude（主） | 架构 / 代码质量 / 逻辑 / 测试 / 前端 / 体验 / 发布 / 运维 | `E:/zxdevelop/project2/novel-agent`（main） | Codex |
| cline | 依赖 / 配置 / 文档 | main（按任务分区） | Claude |
| Codex | 安全 / 合规 / 风险 | main | cline |
| Pi | 性能 | main | cline |
| opencode | 数据 / 数据库 | main | Codex |
| kilo | 接口 / 兼容性 | main | Claude |

---

## 通信方式

- **间接通信**：各 Agent 通过目标工作树的 `.orca/talking.txt` 留言
- **任务分配**：由 Claude（主协调）分析需求后分配到对应能力域的 Agent
- **评审流转**：推荐 Agent 完成后，在评审 Agent 的 talking.txt 留言请求评审

---

## 变更记录

| 日期 | 变更内容 | 操作人 |
|------|---------|--------|
| 2026-08-15 | 初始建立注册表，分配 7 大能力域共 18 个子域 | 用户 |

---

*注册表由用户管理。如需新增能力域或调整分配，请联系用户确认。*
