# Round 7 提案（2026-08-19 规划，Tier 1 + 生产部署）

> 由 Claude (coordinator) 汇总存档。实施范围用户已确认：**Tier 1（#13 专注写作 + #12 灵感套件）+ 生产部署（生产就绪准备）**。

## Round 7 主题

**沉浸创作 + 起点生成 + 生产就绪**——补全"规划 → 沉浸写作"闭环，并清掉长期挂账的生产部署欠账。

## 入选任务

| 编号 | 工具 | 实施 Agent | 评审 Agent | 状态 |
|------|------|-----------|-----------|------|
| R7-1 | #13 专注写作模式（无干扰全屏 + 快捷键体系） | Claude（前端/体验） | codex | 待分派 |
| R7-2 | #12 灵感套件 Creative Kit（世界观+人物+主线设定包一键生成） | Claude（前端/体验） | codex | 待分派 |
| R7-3 | 生产就绪准备（API_KEYS 配置清单 + alembic upgrade 校验 + owner_key_hash 回填脚本 + 部署文档） | cline（配置/文档）+ Claude（运维） | 各域 | 待分派 |

## 规格

### R7-1 专注写作模式（提案 #13）
- 无干扰全屏：隐藏左/右面板，仅保留编辑器 + 顶栏精简
- 快捷键体系：Ctrl+Enter 续写 / Ctrl+S 保存 / Ctrl+\ 全屏切换 / Ctrl+F 查找等
- 落点：`frontend/src/app/novels/[id]/editor/page.tsx`（专注模式 state + 快捷键注册）+ 可能新组件 `FocusModeBar.tsx`
- 验收：TDD（vitest 快捷键/模式切换测试）+ tsc/lint/build ✓

### R7-2 灵感套件 Creative Kit（提案 #12）
- 一键生成完整世界观+人物+主线设定包，替换手动逐项填写
- 复用 R5-1 向导的 useChat 流式 + 现有 world_settings/characters 接口
- 落点：`frontend/src/components/CreativeKitDialog.tsx`（新）+ 设定写入逻辑
- 验收：TDD + tsc/lint/build ✓

### R7-3 生产就绪准备
- `API_KEYS` 配置清单 + `docker-compose.yml` 生产环境变量核对
- `alembic upgrade head` 生产迁移校验（含 owner_key_hash 回填脚本，幂等）
- 部署文档（`deploy/` 更新）
- ⚠️ 腾讯云服务器 2026-08-16 已到期：真实服务器部署待恢复后执行；本轮完成脚本/文档/本地生产模式验证
- 验收：回填脚本幂等可测 + 文档完整

## 未入选（Tier 3 延后）

- #14 创作向导配套
- 遗留建议项：R5-3 哨兵 P2 数据无上限 / P3 日期误报 / P4 频控；R5-4 快照 P2 word_count 语义

## 变更记录

| 日期 | 变更 | 操作人 |
|------|------|--------|
| 2026-08-19 | 规划建立，范围确认（Tier 1 + 生产部署） | Claude + 用户 |
