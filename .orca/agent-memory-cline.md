# Agent Memory — cline（依赖 / 配置 / 文档域）

> cline Agent 的持久化记忆。用于未来轮次快速恢复上下文，避免重复调查。
> 更新规则：每轮完成后将**新的结论/环境事实/工程坑**追加到对应章节；保留旧记录（追加不删改）。

---

## 1. 我的角色与团队

| 项 | 值 |
|----|----|
| 工作树 | `E:/zxdevelop/.orca/worktrees/novel-agent/cline`，分支 `ZX466/cline` |
| 能力域（推荐 Agent） | **依赖 / 配置 / 文档**（评审搭档：Claude） |
| 能力域（评审 Agent） | **安全 / 合规 / 风险**（评审 codex）、**性能**（评审 Pi） |
| Git 身份 | `ZX666X <zx19836980213@outlook.com>`；远程 `gitee`=Gitee(ZX666X)、`origin`=GitHub(ZX466) |
| 项目 | novel-agent：`backend/`(FastAPI+SQLAlchemy, uv)、`frontend/`(Next.js 14 + Tiptap, pnpm/npm) |

团队分工：Claude 主协调/架构/前端、codex 安全、opencode 数据、kilo 接口/兼容、Pi 性能。
任务只通过各工作树 `.orca/talking.txt` 留言流转，不跨板直接执行；行动前必读 `.orca/workflow`、`.orca/agent-registry.md`、本板 `.orca/talking.txt`。

## 2. 协作协议要点（talking.txt 机制）

- 收到 `[任务]`：先回写 `[回复] 状态: 已接受`（不提交会被 merge 拦），再实现；完成记 `[已完成]` + 验证/测试/Git 状态/评审状态。
- 评审只读被评审工作树、结论回写**自己板**；**不提交对方代码、不接管实现**。
- Update Rule：每轮结束精简 talking.txt，只留当前任务/阻塞/最近验证；Claude 协调时全校同步精简版。
- 队列为空时待命，不从历史转录/终端输出/推测中自行生成任务；超出职责域写明「超出范围」退回 Claude。
- 任务块/回复块用 `[任务]/[回复]` + `---` 分隔；板内不粘贴完整日志/令牌/密钥。

## 3. 环境与工程坑（Windows / PowerShell）

- **含 `[id]` 的路径**：PowerShell 视 `[]` 为通配符 → 读取/查找一律 `-LiteralPath`；`cd` 到该目录不可用（找不到路径）。
- **PowerShell 变量赋值**：行首必须是 `$f = '...'`，`[id]` 目录用 `$f = ...` + `Select-String -LiteralPath $f`；不要写成 `.  $f = ...`（报错"后面的表达式生成无效的对象"）。
- 中文内容过 PowerShell 管道需 `$OutputEncoding = New-Object System.Text.UTF8Encoding($false)`，避免 UTF-8 变乱码（曾损坏文件）。
- 后端：`uv run pytest tests/xxx.py -q` 可只跑目标文件（不必全量 ~660 条，快且够评审用）；venv 在 `backend/.venv`。
- Windows 递归删除：先 `[IO.Path]::GetFullPath` 校验目标在工作区内；复杂内联命令用 Python `shutil.rmtree`（先 assert 前缀）。
- Git：GitHub `origin` 常 Connection reset/超时 → 先推 gitee 保数据再重试 origin；只有都成功才能宣称"已推送双远程"。
- merge 时 `.orca/talking.txt` 必冲突（各 agent 板不同）→ `git checkout --ours .orca/talking.txt` 保留本板。

## 4. 依赖 / 配置 / 文档域事实

- 配置类：`backend/app/config.py` 集中管理设置；安全扫描项 `safety_scan_max_chars`（配置键已存在，与提案 #9 对齐）。
- 文档类：`backend/app/api/export.py` 导出接口归属校验 commit `95b865c`（fix(security)），是"补 owner 校验"模式样板。
- 测试定位：`backend/tests/test_safety_scan.py`、`test_export_api.py` 31 项覆盖规则/哈希/缓存/服务/API/租户隔离。
- 前端接线样板：`EditorToolbar`(onOpenRadar/radarStatus) → 编辑器页 `handleOpenRadar/runSafetyScan/handleContinueExport/pendingExportFmt` → `SafetyScanDialog`。

## 5. 安全 / 合规 / 风险域评审要点（我评审 codex 的反复用记忆）

- 租户模型：`owner_key_hash = sha256(X-API-Key)`；所有资源按 owner+novel 双范围隔离；`get_document(id, owner_key_hash)` / `load_parent` 上口校验。
- **无存在性 oracle**：不存在/非本人统一 404/400，错误信息不泄露内部细节。
- 评审必跑：后端相关测试实跑（如 31 passed），确认无 P0；非阻塞建议单列。
- R6-3 状态：**交稿雷达评审已通过**（2026-08-19；结论已回本板）。导出前预检 → findings 弹窗「仍要导出」不阻塞，无 findings 直达导出；规则经 `RuleEngine.register()` 可扩展。

---

*由 cline 维护。追加新结论时保持节号结构，旧记录不删改。*