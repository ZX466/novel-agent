# 配置与文档审查报告：AGENTS.md 策略 + 依赖健康度 + 文档改进

> **执行人**：cline（依赖/配置/文档域 Agent）
> **日期**：2026-08-16
> **任务来源**：Claude 主协调分配（P2，2026-08-16 10:10）
> **评审 Agent**：Claude

---

## 一、AGENTS.md 多版本处理建议

### 1.1 现状

| 项 | 现状 |
|---|---|
| 仓库内 AGENTS.md | 唯一一份，工具无关风格（英文，含 Principles / Architecture Notes / Workflow / Quality 等） |
| 各工具本地配置 | `.claude/`、`.codex/`、`.kiro/`、`.opencode/` 均已加入 `.gitignore`（不入库） |
| CLAUDE.md | 存在于主工作树但未跟踪（Claude Code 的惯例入口文件） |

### 1.2 建议（推荐方案 A）

**方案 A：保持单一 AGENTS.md 为唯一事实源（推荐 ✅）**

- 理由 1：各 Agent 工具（Codex / Kiro / OpenCode 等）普遍按约定读取根目录 `AGENTS.md`，一份工具无关的指令文件可同时服务全部工具，避免多份拷贝漂移。
- 理由 2：工具私有差异（会话缓存、技能配置等）放在各自 gitignore 目录内，天然隔离，不污染仓库。
- 理由 3：符合 AGENTS.md 自身原则"Record durable project knowledge only in existing project documentation. Do not create new top-level docs or duplicate information without a clear need."——为每个工具复制一份全量文档属于无明确需求的重复。

**补充操作建议**：

1. `CLAUDE.md` 若需保留（Claude Code 惯例入口），做成**薄入口**：仅一行引用（如 `See AGENTS.md`）或仅含 Claude Code 特有的少量差异项，不复制全量内容；是否入库由用户决定（当前未跟踪状态也可接受）。
2. 在 README "贡献指南"处已有指向 AGENTS.md 的链接，无需额外文档。
3. 后续若某工具确实需要差异化指令，优先在该工具自己的 gitignore 目录内配置，而非改动入库的 AGENTS.md。

**方案 B（不推荐）：按工具拆分多份 AGENTS-*.md** —— 多份内容 90% 重复，维护成本高，必然漂移。

---

## 二、依赖健康度报告（backend/requirements.txt）

### 2.1 逐项评估（2026-08-16）

| 依赖 | 约束 | 评估 | 说明 |
|---|---|---|---|
| fastapi | `>=0.115` | ✅ 健康 | 下限较新，无已知阻塞问题 |
| uvicorn[standard] | `>=0.30` | ✅ 健康 | — |
| python-multipart | `>=0.0.9` | ✅ 健康 | — |
| langgraph | `>=0.6` | ✅ 健康 | 核心编排依赖，随主版本升级需回归 pipeline 测试 |
| **litellm** | `<1.91` | ⚠️ **有意锁定（保留）** | 见 2.2 专项分析 |
| sqlalchemy[asyncio] | `>=2.0.30` | ✅ 健康 | asyncio extra 必需 |
| asyncpg | `>=0.29` | ✅ 健康 | — |
| alembic | `>=1.13` | ✅ 健康 | 迁移链正常（Codex 安全修复新增 c4d5e6f7a8b9） |
| pgvector | `>=0.3` | ✅ 健康 | HNSW + 半径过滤已验证可用（Pi 优化依赖 `<=>` 运算符） |
| redis | `>=5.0` | ✅ 健康 | Codex 第二轮速率限制将基于 Redis，版本满足 |
| pydantic | `>=2.7` | ✅ 健康 | — |
| pydantic-settings | `>=2.3` | ✅ 健康 | — |
| httpx | `>=0.27` | ✅ 健康 | litellm 与测试共用 |
| pytest | `>=8.0` | ✅ 健康 | — |
| pytest-asyncio | `>=0.23` | ✅ 健康 | — |

### 2.2 `litellm<1.91` 硬约束专项分析

- **约束来源**：README §8 与 AGENTS.md 均明确记载——"1.91+ 引入 Rust 组件"，会显著复杂化 Windows 本地开发环境（当前团队主力为 Windows + uv）。
- **结论**：**合理，应保留**。这是有意的技术决策而非陈旧 pin。
- **风险与对策**：
  1. 上限锁定意味着无法自动获得新版本的安全修复。**对策**：每次 litellm 官方发布安全通告（GitHub Advisories）时，由 cline 域评估：若受影响版本区间覆盖 <1.91，则寻找可用的补丁回移版本；若必须升级到 1.91+，需先在团队内确认 Rust 工具链可行性，作为独立变更走评审。
  2. 建议在 CI 或季度任务中加入 `pip-audit`（仅审计，不升级）扫描已安装版本的已知漏洞，输出到依赖域归档。
- **净增依赖提醒**：Codex 第二轮将引入 `nh3`（content_html 净化）。该依赖为 Rust 绑定但提供预编译 wheel，Windows 下 `uv pip install` 可直接安装，与 litellm 的 Rust 顾虑不同类，**可接受**。

### 2.3 结构性改进建议（P3，可选）

1. **测试依赖分离**：pytest / pytest-asyncio 移入 `requirements-dev.txt` 或 pyproject 的 optional-dependencies，生产镜像可瘦身。当前规模影响小，优先级低。
2. **锁文件**：当前全部为下限约束，无锁定文件。建议用 `uv pip compile requirements.txt -o requirements.lock`（CI 中生成），保证腾讯云部署与本地可复现。与项目 uv 工作流契合。

---

## 三、文档改进建议（QUICKSTART 评估等）

### 3.1 QUICKSTART.md 评估结论：**需要，已创建 ✅**

- **理由**：README 约 320 行，信息完整但"首次配置"埋在第一节且混合了背景说明；新协作者（或新 Agent 工作树）需要一个 30 秒可扫完的最短路径。
- **已交付**：`QUICKSTART.md`（项目根目录，1 页）：隧道 → 后端 → 前端 → 验证清单 → 常见坑。与 README 内容同源不冲突，README 保留完整细节。
- **联动更新**：README 顶部已补一行指向 QUICKSTART.md（见本次提交）。

### 3.2 其他文档观察（不阻塞，记录备查）

| 项 | 观察 | 建议 |
|---|---|---|
| CHANGES.md / CHANGES-2026-07-20.md | 双文件并存，前者为主日志 | 保持现状；下次大版本时合并旧文件内容 |
| deploy/README.md | 服务器部署独立成文，结构清晰 | 无需改动 |
| backend/docs/ | 本报告建立该目录 | 后续域报告（如 kilo 的 api-review.md）建议统一放此处 |

---

## 四、交付物清单

| 文件 | 状态 | 说明 |
|---|---|---|
| `QUICKSTART.md` | ✅ 新增 | 1 页快速上手 |
| `backend/docs/CONFIG-REVIEW.md` | ✅ 新增 | 本报告 |
| `README.md` | ✅ 微调 | 顶部加 QUICKSTART 入口链接（1 行） |
| `requirements.txt` | 未改动 | 依赖评估结论为"保留现状"，无版本变更需求 |
| `AGENTS.md` | 未改动 | 建议保持单一版本（方案 A），无代码级变更 |

## 五、验证方式

- 纯文档变更，无运行时影响。
- QUICKSTART.md 步骤与 README §一（首次配置）逐条比对一致（uv venv → activate → uv pip install → alembic upgrade → uvicorn；前端 npm install → dev）。
- 健康检查路径按 kilo 第二轮已统一的 `/v1/health` 书写（与当前 ZX466/kilo 分支一致）。
