# Agent Memory — cline（依赖 / 配置 / 文档）

> 供 cline 后续会话快速恢复上下文。行动前仍须先读 `.orca/workflow`、
> `.orca/agent-registry.md` 和 `.orca/talking.txt`（留言板以 talking.txt 为准）。
> 更新规则：每轮完成后把**新结论/环境事实/坑**追加到对应章节；旧记录不删改。

## 1. 我的角色与团队

- 能力域：**依赖 / 配置 / 文档**（评审搭档 Claude）；同时是 Codex（安全/合规/风险）与 Pi（性能）的评审搭档。
- 工作树：`E:/zxdevelop/.orca/worktrees/novel-agent/cline`，分支 `ZX466/cline`，基于 main。
- 多 Agent 协作：Claude（主协调/架构/前端）、codex（安全）、opencode-2（数据/数据库，旧 opencode 为进程占用空壳）、
  kiro（接口/兼容，旧 kilo 改名）、Pi（性能）。任务只通过各工作树 `.orca/talking.txt` 留言流转，不跨板直接执行。
- Git 身份：`ZX666X <zx19836980213@outlook.com>`；远程 Gitee=`gitee`、GitHub=`origin`。

## 2. 协作协议要点

- 收到 `[任务]`：先回写 `[回复] 状态: 已接受` 并提交，再实现；完成后只记录结论、验证、Git 状态、评审状态。
- 评审（我评审 codex / pi）：只读被评审工作树、把结论回写到**对方板**；**不改对方代码、不代提交**；非阻塞微瑕单列备注。
- 队列为空待命，不从历史转录/终端输出自行生成任务；超出注册表职责写"超出范围"退回 Claude。
- GitHub(origin) 443 reset/timeout：**不要循环重试推送**，只记录"待补推"，等网络恢复后补推；Gitee 正常。
  不得把未验证的推送写成完成（"双推成功才算完成"）。
- `.orca` 是唯一被跟踪的顶层隐藏目录；提交用 Conventional Commits（chore/docs/feat/refactor/perf…）。

## 3. 环境与工程坑（本会话实测，2026-09-10）

- **npm 12 `EALLOWREMOTE` 环境策略**：`npm ci`/`npm install` 均被拦截，node_modules 无法重建 →
  `npx tsc --noEmit`/vitest 在本地**跑不了**；需要时写"待网络/CI 补跑"，或用已有 node_modules 的主工作树。
- **PATH 无 python**（`python -m py_compile` 报 9009）：语法校验用 `uv run --no-project python -m py_compile <files>`（uv 0.12.3 可用）。
- **docker CLI 可用**：v29.7.2 / compose v5.5.1；`docker compose -f docker-compose.yml config` 可离线校验语法（exit 0=通过）。
  - 主 compose 校验前若 `backend/.env` 缺失（清理轮已删待重配）会报 env_file 错误——可临时建空 `backend/.env` 校验后删除。
  - local compose 的 `${VAR:?}` 必填项需临时设 dummy 环境变量再校验。
- **PowerShell + 中文管道必踩坑**：向 Python 管道传中文前先 `$OutputEncoding = New-Object System.Text.UTF8Encoding($false)`，
  否则 UTF-8 被破坏（R5-4 曾损坏 4 个前端文件）。
- **写无 BOM 文件**：`Set-Content -Encoding UTF8` 会加 BOM 且把 LF 变 CRLF；改用
  `[IO.File]::WriteAllText($p,$t,(New-Object System.Text.UTF8Encoding($false)))`。
- **路径根是 `E:\zxdevelop`**（不是别的拼写）；曾因拼错盘符导致多次 ENOENT。
- 读取含 `[id]` 的路径用 `-LiteralPath`/read_files 时不加通配。
- **工具怪癖**：shell 偶发把 `git worktree list` / `git branch -l` 输出替换成 `[dedup:ref ...]`；
  需要完整输出时写文件再读：`git worktree list > $env:TEMP\wt.txt 2>&1; Get-Content $env:TEMP\wt.txt`。
- **分支收敛踩坑（团队级）**：曾出现 4 个同内容不同 hash 的重复板面提交（`88d22cc`/`e72f2f8`/`394dba2`/`efc1cfa`）；
  避免多会话并发改同一板面；收敛用 `git reset --hard <正确 hash>` + 一次强制推 main。

## 4. 测试与验证基线（截至 R8 / 2026-09-10）

- 后端：`uv run pytest tests/` → **824 passed / 1 skipped**（旧记录 660 已过时；偶发收集期 MemoryError 重跑即可）。
- 前端：`npx tsc --noEmit`、`npm run lint`、`npm run test`（vitest 39 passed）——本地受 EALLOWREMOTE 限制，需已有 node_modules。
- 迁移：`uv run alembic upgrade head`；`uv run alembic heads` 须单头（链 f6a7b8c9d0e1）。

## 5. R9 状态（2026-09-10，curl 前对照 talking.txt）

- R9-① 全局改名 Project11 → novel-agent：**已完成**（commit `b4b40a8`，14 文件，gitee 已推，origin 待补推）。
  - 改了：compose 容器名 ×7、README/CHANGES/docs/diagrams/deploy scp 路径/nginx 注释、backend 日志×2+title+docstring+requirements+pyproject description、frontend title+NavBar(含 logo P→N)+SettingsDialog placeholder。
  - **保留并注释**（改了丢数据/属行为面）：POSTGRES_DB 默认、REDIS_PASSWORD 默认、localStorage `project11:*` keys、包名 project11-backend/-frontend（lock 同步 churn）、test 夹具、历史记录。
  - 验证：grep 残留仅必要处；compose config 两文件 exit 0；uv py_compile 0；tsc 未跑（EALLOWREMOTE）。
- R9-② codex 事件流协议 v1 评审：**已完成**（结论回写 codex 板；我的提交 `0f725dd`）。
  - 结论：通过（可实施）。核验 SSE 兼容（perf-transport.ts default 忽略未知 type；队列 str→(kind,payload) 仅影响 _event_stream）、
    summary 白名单用闭合白名单加固、failed code 建议 `llm_auth|llm_rate_limit|llm_timeout|llm_context_length|stage_error`、
    64 条上限合理（最坏 generate+max_iters=10 → 46 条）。M1：skipped 必须由 pipeline 层发（非活动节点不在图中）；
    M2：非流式 fallback 无 stage 事件，前端需容忍。
- R9-⑤ AI 插入分段丢失：诊断**已完成**（建议归 Claude 实施）。根因 `editor/page.tsx:617` 等 5 处
  `insertContent(纯文本)` 按 HTML 解析折叠 `\n`；方案 `textToParagraphNodes()` 节点数组（逐 `\n` → paragraph 节点，空行→空段）。

## 6. 命名决策记录（改名轮，避免重查）

| 项 | 处置 | 原因 |
|----|------|------|
| POSTGRES_DB 默认 project11 | 保留+注释 | 数据库名绑定卷内既有数据，改则旧数据不可见 |
| REDIS_PASSWORD 默认 project11-redis | 保留+注释 | redis↔backend 共享凭据，属行为面 |
| localStorage `project11:*` keys | 保留 | 改则丢用户主题/写作目标/草稿 |
| pyproject/package.json name | 保留 | 代码标识符；uv.lock/package-lock 同步 churn |
| AGENTS.md/agent-memory/PERFORMANCE-ANALYSIS 中旧名 | 保留 | 历史记录 |
| `-d project11`（deploy README） | 保留+注释 | 数据库名 |