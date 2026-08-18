# Round 5 创作工具提案汇总（2026-08-18）

> 目的：完善但简化创作流程。各 Agent 按能力域提出新颖创作工具提案（仅提案，不实现）。
> 本文件由 Claude (coordinator) 汇总存档；各板 talking.txt 已精简，细节以本文件为准。

## 已回收 5/5

### cline — 配置/文档视角（2 项）
1. **创作配方卡 Recipe Cards**：按创作意图组织编号卡片（01 新书三步开写 / 02 续写旧稿 / 03 喂知识库 / 04 导出投稿 / 05 换模型供应商），每卡=目标+3-5 步+一行验证+常见坑，自包含不跳转。落点：`docs/recipes/*.md`（首发 5 卡）+ QUICKSTART 顶部索引。
2. **最小可用配置分层 Layered Config**：变量按 `[必填-最小]`/`[可选-增强]`/`[可选-调优]` 重排注释，配 CONFIG-MATRIX.md（场景×变量×必/可选×默认×不配后果）。落点：`backend/.env.example`（仅注释）+ `backend/docs/CONFIG-MATRIX.md`。

### opencode — 数据/数据库视角（2 项）
3. **设定一致性哨兵**：草稿入库后自动 RAG 检索该角色历史设定，比对数值/性格/关系变化，产出"疑似矛盾"列表附证据 chunk，一键定位返工点。落点：`backend/app/services/consistency.py` + `consistency_checks` 表，复用 retrieval 5 集合。
4. **时间线图谱**：`plot_events` 增 `in_world_date` 与 `prev_event_id` 前驱指针，自动构建因果 DAG；章节写入校验前置事件满足性与倒序/环路，冲突实时告警。落点：迁移扩展 `plot_events` + `backend/app/services/timeline.py` + 时间线视图接口。

### pi — 性能视角（2 项）
5. **PerfPulse 性能自监控面板**：pipeline 各阶段耗时（RAG/embed/draft/refine/TTFT）实时显示在编辑器状态栏，优化透明化。落点：`backend/app/pipeline/nodes.py` 收集耗时 → `frontend/src/components/Editor.tsx` 状态栏。
6. **DocLite 超长文档零卡顿**：EditorStats 防抖+useMemo（<16ms）+ word_count 服务端增量缓存 + Tiptap 分块惰性渲染。落点：`frontend/src/components/Editor.tsx` + `backend/app/services/document.py`。

### kilo — 接口/兼容性视角（2 项）
7. **多平台导出适配器**：`/v1/documents/{id}/export` 扩展 format 枚举（qidian/jj/zhihu/wechat），按平台模板渲染封面/分卷/署名/版权声明。落点：复用 `backend/app/api/export.py` + 新增 `backend/app/services/export_adapters/` 层。
8. **创作数据可移植网关**：`format=ndjson` 全量导出 + `/v1/documents/import` 幂等导入（按 chapter_id upsert）+ last_sync 游标增量同步。落点：`backend/app/api/export.py` + 新增 `backend/app/api/import.py` + `services/portable.py`。

### codex — 安全/合规视角（2 项）
9. **交稿雷达**：仅在导出或主动点击时检查隐私/版权/敏感表达提示并缓存结果，不阻塞保存或写作。落点：`backend/app/safety/rules.py` + `frontend/src/components/EditorToolbar.tsx`。
10. **安心回溯**：AI 插入、整章替换和导出前自动建快照，历史面板一键对比/恢复，降低误改焦虑。落点：`frontend/src/app/novels/[id]/editor/page.tsx` + `frontend/src/components/VersionHistoryDialog.tsx`。

### Claude — 架构/前端/体验视角（4 项）
11. **创作向导 Wizard**：题材→大纲→分章→正文 一体式引导，5 步手动操作收成 1 个流程。
12. **灵感套件 Creative Kit**：一键生成完整世界观+人物+主线设定包，替换手动逐项填写。
13. **章节脑图**：大纲可视化 + 拖拽排序 + 直接续写入口。
14. **专注写作模式**：无干扰全屏 + 快捷键体系。

## 评审状态（2026-08-18 定稿）

✅ 用户确认 **Round 5 实施范围 = Tier 1 核心 5 项**（其余留待后续轮次）：

| 入选 | 工具 | 实施 Agent | 评审 Agent |
|------|------|-----------|-----------|
| #1 | 创作向导 Wizard | Claude（前端/体验） | codex |
| #2 | 创作配方卡 Recipe Cards | cline（文档） | Claude |
| #3 | 设定一致性哨兵 | opencode（数据/数据库） | codex |
| #6 | DocLite 超长文档零卡顿 | pi（性能） | cline |
| #7 | 多平台导出适配器 | kilo（接口/兼容性） | Claude |
| #10 | 安心回溯（快照+版本历史） | codex（风险缓解） | cline |

未入选本轮（Tier 2/3）：#4 时间线图谱、#5 PerfPulse、#8 数据可移植网关、#9 交稿雷达、#11-14（章节脑图/灵感套件/专注模式/创作向导配套）。
评审维度：创新度 / 流程简化收益 / 实现成本 / 依赖关系（如 3↔4 共享检索与事件模型、7↔8 共享导出层）。
