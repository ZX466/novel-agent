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

## 6. 工作流规则（用户定稿，跨对话永久生效；每次行动前必读 `.orca/workflow` + `.orca/agent-registry.md`）

- **总则**：Claude 占主导、起组织作用；每个能力域只指定一个推荐 Agent + 一个评审 Agent，不重复分配；未覆盖能力保持空白，由用户决定补充。
- **沟通**：Agent 之间尽量不直接对话；有必要时通过各工作树 `.orca/talking.txt` 间接留言。
- **不得越界**：行动前先读 `.orca/workflow.txt`，只做自己能力域内的事。
- **注册表**：`.orca/agent-registry.md` 为准——架构/代码质量/逻辑/测试=Claude(推荐)/Codex(评审)；依赖/配置/文档=cline/Claude；安全/合规/风险=Codex/cline；性能=Pi/cline；数据/数据库=opencode/Codex；接口/兼容性=kilo/Claude；前端/体验/发布/运维=Claude/codex。我（codex）= 安全/合规/风险推荐 Agent；评审域含架构/代码质量/逻辑/测试、数据/数据库、前端/体验/发布/运维。注册表由用户决定，不随意更改。
- **Git 身份**：提交姓名 `ZX666X`，邮箱 `zx19836980213@outlook.com`（绑定 Gitee=ZX666X + GitHub=ZX466，一条提交同归两平台）；机器全局已配置，新 clone 无需再配。
- **Python 必须用 uv**：用 `uv` 建虚拟环境并在其中构建（必要项）。
- **隐藏目录**：除 `.orca` 外，其它 `.` 开头的目录/文件一律不入 git、不推送。
- **上下文预算**：context 使用达到 50% 时主动提醒切换新对话，最大限度节省用户 token。
- **任务流**：Claude 通过 talking.txt 分配 `[任务]`；Agent 回写“已接受”后立即执行；执行后回写结论（安全结论/验证/Git 状态/评审状态）。
- **留言板维护**：每几轮对话检查全部工作树的 `.orca/talking.txt`，删除无用内容避免干扰，保持各板同步精简版。
