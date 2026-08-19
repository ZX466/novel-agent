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

## 7. Round 6 复盘与持久记忆（2026-08-19）

- **R6-1 章节脑图复核通过**：Claude 修复提交 `25fe403` 解决了向下拖拽删除源节点后的插入索引错误；脑图节点支持 `role="button"`、`tabIndex`、Enter/Space 选择、ArrowUp/ArrowDown 排序，续写按钮有 `aria-label`，视图切换有 `aria-pressed`，空状态可添加第一章。前端新增 Vitest + Testing Library；复核时 `npm test -- --run` 为 8 passed，`npx tsc --noEmit`、`npm run lint`、`npm run build` 均通过（lint/build 仅有既有字体警告）。
- **R6-2 时间线图谱第二轮复审通过**：opencode 提交 `03d62e1` 已解决此前阻塞项；本记忆只记录“复审通过”，不要在未由 Claude 合入 main 前声称已合并。该轮测试快照为 `794 passed / 1 skipped`，其中 `tests/test_timeline.py` 为 36 passed。
- **跨作品前置事件防线**：`prev_event_id` 必须在 service 层按 `id + novel_id` 校验，并在数据库层使用 `(novel_id, prev_event_id)` 到 `(novel_id, id)` 的复合 FK；不存在和跨作品前置事件应统一报错，避免事件 ID 存在性侧信道。
- **复合 FK 删除陷阱**：PostgreSQL 对复合 FK 的普通 `ON DELETE SET NULL` 会尝试清空全部本地引用列，连同 NOT NULL 的 `novel_id` 一并置空而失败。删除前置事件前，必须在同一事务中先把同作品后继的 `prev_event_id` 显式置 NULL，再删目标；此行为需要真实 PostgreSQL 集成测试，而不能只依赖 mock。
- **时间线告警刷新**：更新/删除事件时，受影响章节应取 `chapter_id ∪ chapter_index`，并覆盖旧事件位置、旧前置事件和新前置事件；没有告警时必须移除 `metadata_json["timeline_warnings"]`，避免残留状态。
- **时间线资源上限**：`settings.timeline_max_events` 默认 5000；`get_timeline()` 先 count，超过上限由 API 返回 413；章节写入的告警检查则 best-effort 跳过。后续可关注 count→select 并发窗口和 summary 的字节级响应限制。
- **迁移与真实 DB**：时间线链的目标 head 为 `c0d1e2f3a4b50`。子工作树通常没有 `.env`；运行真实 DB Alembic 时从主工作树 `backend/.env` 读取环境变量，绝不猜测或记录密码。`alembic heads/current/upgrade head` 都需要实际环境变量，失败原因应区分“未加载 env”和“真实迁移错误”。
- **Token / 上下文纪律（用户明确要求）**：每个 Agent 在上下文接近 50% 时主动提醒切换新对话；切换前将当前任务、提交、验证、阻塞和待复审结论压缩写入 `.orca/agent-memory-*.md` 与相应 `talking.txt`。只写可复用事实，不写密钥、完整终端日志或冗长会话转录。

## 8. Round 7 前端复审经验（2026-08-19）

- **专注模式快捷键必须有可见结果**：若专注模式隐藏了右侧 AI 工具栏，`Ctrl+Enter` 仅修改隐藏的 tab state 就是静默 no-op。任何在 FocusModeBar 中展示的快捷键都应做端到端状态测试，确认目标面板/对话框实际可达；保留的旧快捷键也必须统一走 Ctrl/Meta 归一逻辑。
- **子组件写入后必须同步父级文档状态**：子组件 `updateDocument()` 成功却丢弃返回的 `EditorDoc`，而父级之后用陈旧 `doc.metadata_json` 整体 PATCH，会静默覆盖刚写入的 outline。JSON metadata 的读改写须把最新结果回传并更新单一事实来源；有并发保存时优先使用服务端原子 merge 或版本/冲突控制。
- **LLM 批量写入的完整性边界**：逐条调用会各自提交；任一条的字段校验、网络或服务错误都会留下部分持久化数据，重试会重复创建。对 LLM 解析结果先限制条数、长度和对象类型，跨多实体的一键“应用”优先后端原子批量 API，或明确幂等键/补偿策略。
- **LLM 内容的展示边界**：React 普通文本插值默认转义，且不得把生成文本转入 `dangerouslySetInnerHTML`；仍需为弹窗提供 `role="dialog"`/名称、初始焦点、焦点返回和 Escape，不能把“已渲染”误当成“可访问”。