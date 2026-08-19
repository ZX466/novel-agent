# Codex 记忆笔记（Security / Compliance / Risk）

> 供 codex Agent 后续会话快速恢复上下文。行动前仍须先读 `.orca/workflow`、
> `.orca/agent-registry.md` 和 `.orca/talking.txt`（留言板以 talking.txt 为准）。

## 1. 我的角色与团队

- 能力域：**安全 / 合规 / 风险**（评审搭档 cline）；实现由 Claude 分配，评审通过后 Claude 合并到 main。
- 工作树：`E:/zxdevelop/.orca/worktrees/novel-agent/codex`，分支 `ZX466/codex`。
- 多 Agent 协作：Claude（主协调/架构/前端）、cline（配置/文档/依赖）、opencode（数据/数据库）、
  kilo（接口/兼容）、Pi（性能）。任务只通过各工作树 `.orca/talking.txt` 留言流转，不跨板直接执行。
- Git 身份：`ZX666X <zx19836980213@outlook.com>`；远程 Gitee=`gitee`、GitHub=`origin`。

## 2. 协作协议要点

- 收到 `[任务]`：先回写 `[回复] 状态: 已接受`，再实现；完成后只记录安全结论、验证、Git 状态、评审状态。
- 评审只读被评审工作树、回写结论到其板；**评审不接管实现、不提交对方代码**。
- 队列为空时待命，不从历史转录/终端输出自行生成任务。
- `.orca` 是唯一被跟踪的顶层隐藏目录；提交用 Conventional Commits。

## 3. 环境与工程坑（重要）

- **PowerShell + 中文管道必踩坑**：向 Python 管道传递含中文内容前，必须先执行
  `$OutputEncoding = New-Object System.Text.UTF8Encoding($false)`，否则 UTF-8 会被破坏成 `?`/乱码
  （R5-4 曾因此损坏 4 个前端文件）。可靠写入模式：`@'...'@ | python -` 配合 Python `open(..., encoding="utf-8")`。
- 后端测试：`uv run pytest`（基线约 660 passed / 1 skipped）。前端验证：`npx tsc --noEmit`、`npm run lint`、`npm run build`。
- Windows 递归删除：先 `[IO.Path]::GetFullPath` 校验目标在工作区内，再删；复杂 PowerShell 内联命令易被
  策略拦截——改用 Python `shutil.rmtree`（先 assert 路径前缀）。
- 读取含 `[id]` 的路径用 `-LiteralPath`（PowerShell 会把 `[id]` 当通配符）。

## 4. 安全架构事实（novel-agent 后端）

- 租户模型：`owner_key_hash = sha256(X-API-Key)`；所有文档/章节/角色/检索均按 owner + novel 双范围隔离。
- 归属校验模式（R5-3 P1 教训）：查询按 `novel_id` 限定 + **取回后二次校验**（防御性双实现）；
  不存在/非本人同报同一错误（404/400），**无存在性探测面**；API 入口先 `load_parent` 校验归属。
- 错误信息不泄露内部细节；快照/一致性检查写入前 best-effort 且不阻塞主流程。
- 复用模式参考：`get_document(id, owner_key_hash)`、`_chapter_text(session, chapter_id, novel_id)`、
  `_collect_evidence -> retrieve(novel_id=...)`、`enforce_chat_rate_limit`。

## 5. Round 5 状态（截至 2026-08-19）

- R5-4 安心回溯（自动快照 + 版本历史）：**已合入 main**（`8094a5d`，评审 cline 通过）。
- R5-3 设定一致性哨兵：P0 跨租户读取修复（`c02846d`）**复审通过**，结论已回 opencode 板；可合入 main。
- 遗留建议（非阻塞）：consistency_checks 无保留策略 / 日期年份数值误报（"2026 年"）/ check 端点无频控。
