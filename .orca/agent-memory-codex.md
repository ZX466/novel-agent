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
- R5-3 设定一致性哨兵：P0 跨租户读取修复（`c02846d`）**复审通过并已合入 main**。
- 遗留建议（非阻塞）：consistency_checks 无保留策略 / 日期年份数值误报（"2026 年"）/ check 端点无频控。

## 6. 2026-09-09/10 结构、运维与网络纪律（新增）

- **工作树拓扑（2026-09-10 重建）**：主工作树 `E:/zxdevelop/project2/novel-agent` = `main`；agent 工作树
  `cline`/`codex`/`kiro`/`opencode-2`/`pi` 各挂 `ZX466/<同名>` 分支，均基于 main。kilo→`kiro`、
  opencode→`opencode-2`（旧 `opencode` 目录为进程占用的空壳）。codex 工作树 HEAD 与 main 同为 `d36d1dd`。
- **dot 目录策略**：`.agents/`、`.codegraph/` 是指向主工作树的 junction（gitignore，不入库）；
  `.kiro/`、`.opencode/` 是**已跟踪例外**（`96f99d2` 入库）；`.codex/` 已解除忽略但目录为空。
- **GitHub(origin) 网络纪律**：443 reset/timeout 时**不要循环重试推送**，只记录“待补推”，
  等网络恢复后补推；Gitee 正常。汇报里不得把未验证的推送写成完成。
- **分支收敛踩坑**：曾出现 4 个同内容不同 hash 的重复板面提交
  （`88d22cc`/`e72f2f8`/`394dba2`/`efc1cfa`，均基于 `981daf3`）；收敛方式
  `git reset --hard <正确 hash>` + 一次 `git push gitee +<hash>:main`。避免多会话并发改同一板面。
- **测试基线更新**：R8 之后为 **824 passed / 1 skipped**（本文件旧记 660 已过时）。
- **文档写入**：`Set-Content -Encoding UTF8` 会加 BOM 且把 LF 变 CRLF；改用
  `[IO.File]::WriteAllText($p,$t,(New-Object System.Text.UTF8Encoding($false)))` 保持无 BOM。
- **工具怪癖**：本 shell 偶发把 `git worktree list` / `git branch -l` 输出替换成 `[dedup:ref ...]`；
  需要完整输出时写文件再读：`git worktree list > $env:TEMP\wt.txt 2>&1; Get-Content $env:TEMP\wt.txt`。

## 7. Round 6–8 与审计二批（安全视角，截至 2026-09-10）

- **R8 安全加固 + 消债轮已归档**：`c8bc383`（L2 依赖精确 pin + L6 CI 安全门禁 + TOCTOU 文档化）、
  `9c16760`，合入 main 后回归 **824 passed / 1 skipped**。
- **审计遗留二批（L1/L3/L5/L8）全部完成并通过交叉评审**：
  - L1 迁移自动化（opencode 实现 → codex 复评通过）：`check_migrations.py` 单头校验 + 未应用检查 + 失败 loud。
  - L3 `_event_stream` 误报（codex 实现 → cline 通过）：新增 `APIBaseNotAllowed` 专用异常，收敛 SSRF 捕获面。
  - L5 CSP nonce（codex 实现 → cline 通过）：middleware 每请求生成 nonce，nginx 下发同 nonce CSP。
  - L8 `API_KEYS` 缺省态（cline 实现 → codex 通过）：缺省时 503 + 引导文案，配 2 个测试。
- **验证命令参考（评审时实际用过）**：`uv run pytest tests/`（后端全量）；
  前端 `npx tsc --noEmit`、`npm run lint`、`npm run test`（vitest 39 passed）。
- **评审纪律**：只读被评审工作树 + 回写结论，不改对方代码、不代提交；非阻塞微瑕单列备注，不阻塞合入。
