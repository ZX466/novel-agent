# OpenDesign 重构前端提示词（novel-agent）

> 用途：交给 OpenDesign（或任何前端重构代理）做 novel-agent 前端重构时的完整上下文提示词。
> 生成：2026-09-12，基于 R9 收口后 main（efbdd6f）的实际代码状态与用户实测反馈。
> 使用方式：整体作为系统提示/首条消息投喂；`【】`小节可按重构范围裁剪。

---

## 【角色与目标】

你是前端重构设计师。目标项目 **novel-agent**：AI 小说创作平台（Next.js 14 + React 18 + TipTap + AI SDK v5 + Tailwind CSS 变量令牌）。当前前端已功能可用但存在布局碎片化、组件缺失、视觉层级混乱三类问题。你的任务是**在不破坏现有功能契约的前提下重构前端**：统一设计系统、补齐缺失页面、优化信息架构。

**铁律：先读后改。** 任何组件改动前必须读它的数据流（调哪些 API、消费哪些 SSE 事件、localStorage 键名）。下方"不可破坏契约"清单是红线。

## 【项目结构】

```
frontend/src/
├── app/                      # Next.js App Router
│   ├── page.tsx              # 首页（落地页）
│   ├── layout.tsx            # 根布局（NavBar + 主题: novel-agent:theme, dark/light/eye-care）
│   ├── novels/page.tsx       # 作品列表页
│   ├── novels/[id]/editor/page.tsx   # ★核心: 写作工作台（1300+ 行,重构首要目标）
│   └── stats/page.tsx        # 创作统计看板（用户反馈"没看见"——入口埋没）
├── components/               # 全部 UI 组件（约 30 个）
├── lib/
│   ├── settings.ts           # BYOK 配置/localStorage/请求头（勿动契约）
│   ├── perf-transport.ts     # ★SSE 自定义 transport（勿动解析逻辑）
│   ├── insert-text.ts        # 文本↔段落节点/HTML 转换（勿动转换规则）
│   ├── types.ts              # 领域类型+工具预设
│   └── api 客户端们          # documents/chapters/characters/plot-events 等
└── hooks/                    # use-provider-config 等
```

## 【不可破坏契约（红线）】

1. **SSE 流协议 v2**：后端发 `data:` JSON 行 + `data: [DONE]`。chunk 类型：AI SDK 标准类型 + `data-stage`/`data-pipeline_start`/`data-perf`（data 包裹原始载荷）。**所有聊天类组件必须用 `PerfChatTransport`**（`lib/perf-transport.ts`）——AI SDK v5 的 `DefaultChatTransport` 严格校验 chunk type，裸自定义类型会炸流。`PerfChatTransport` 构造参数：`{api, headers, onPerf, onStage, extraBody}`。
2. **BYOK 请求头**：每个请求带 `X-Provider-Config`（JSON 序列化的 `ProviderConfig`：draft/refine/evaluate 必填、embedding 可选——**三阶段必须都有值否则后端 422**）+ `X-API-Key`（ownerAuth）。构造函数见 `lib/settings.ts` 的 `loadProviderConfig()`/`ownerAuthHeaders()`。
3. **localStorage 键前缀 `novel-agent:`**：`novel-agent:provider-config`、`novel-agent:api-key`、`novel-agent:theme`、`novel-agent:ai-draft:<novelId>`（AI 草稿暂存）。更名后旧键 `project11:` 不再读取——迁移逻辑需保留。
4. **章节正文是纯文本**（段落间 `\n\n`）：加载时必须过 `textToTipTapHTML()` 再 `setContent()`；AI 插入必须用 `textToParagraphNodes()` 节点数组（不能用 `insertContent(string)`——会塌段落）。
5. **R9-④⑥ 章节字段**：聊天请求体带 `chapter_index/total_chapters/chapter_title/target_word_count`（snake_case，null 容忍），经 `PerfChatTransport` 的 `extraBody()`。
6. **后端 API 前缀 `/v1`**，nginx 反代；错误处理：422 带 `detail` 字段级数组、409 冲突、SSE 内 `error` part 带 `detail`——UI 必须透传具体文案（禁止笼统"服务暂时不可用"）。

## 【现有页面/组件清单与已知问题】

### 编辑器工作台 `novels/[id]/editor/page.tsx`（1300+ 行，重构核心）
- 左栏 4 tab：大纲(outline)/人物(characters)/世界观(world)/剧情事件(events)
- 右栏 2 tab：AI 工具(AIToolPanel)/AI 编剧(AssistantPanel)
- 中间 TipTap 编辑器 + 章节切换 + 快照历史 + 专注模式
- **问题**：单文件 1300+ 行；tab 数量少但每个面板内功能密度不均；AI 工具面板信息层级混乱（工具按钮/表单/输出/进度挤在一起）

### 已有组件（保留功能，可重写视觉）
NavBar（3 入口）、SettingsDialog（4 阶段 BYOK 配置+测试连接+快速模板）、AIToolPanel（6 工具+阶段进度 StageProgress+字数控制表单）、AssistantPanel（多轮编剧对话）、CreationWizard（设定→大纲→应用 三步向导）、CreativeKitDialog（灵感套件：一键生成任务/标题/世界观等）、OutlineMindMap（大纲脑图 SVG）、StageProgress（五阶段进度）、StatsDashboard（统计）、VersionHistory、SafetyScanDialog、EditorStats

### 后端 API 已就绪但【前端 UI 缺失】（重构必须补齐的页面/组件）
1. **人物关系图**（R9-③）：后端 `/v1/documents/{id}/character-relationships` 有 graph/PUT/DELETE/import 4 端点，数据结构 `{characters:[{id,name,role}], relationships:[{subject_id,object_id,relation_type,strength,description}]}`。需要：力导向/层级关系树可视化、拖拽改关系、冲突 409 提示。
2. **时间线图谱**（R6-2）：`/v1/documents/{id}/timeline` 因果 DAG + `in_world_date`。需要：DAG 可视化、按世界内日期排列、事件详情。
3. **设定一致性哨兵**（R5-3）：`/v1/documents/{id}/consistency/check` + checks 列表。需要：检查入口、结果面板（数值比对差异高亮）。
4. **统计看板入口**：`/stats` 页面存在但导航层级弱——需在编辑器内也提供入口。

## 【用户实测反馈的问题清单（重构优先级依据）】

1. 关系图/时间线/一致性 UI 缺失（上面 1-3）
2. 统计页入口埋没
3. AI 生成链路曾因 transport 报错/界面无进度——已修，但 UI 需保持：生成中显示 StageProgress 五阶段，失败显示服务端具体 detail
4. 409 重复导入无友好提示（创作向导重复"应用"时）——需 toast/inline 提示"已存在，已跳过"
5. embedding 慢导致实体入库卡顿——实体保存需 loading 态与后台化提示

## 【设计系统约束】

- 主题三态：dark（默认）/light/eye-care，全部颜色经 CSS 变量（`var(--bg)`/`var(--surface)`/`var(--border-subtle)`/`var(--fg-secondary)`/`var(--accent)`/`var(--danger)`/`var(--warn)`/`var(--muted)` 等，定义在 `globals.css`）。重构不得硬编码颜色，全部走变量。
- 间距体系：`px-sp-N`/`py-sp-N`/`gap-sp-N` 工具类（sp 令牌）。
- 中文优先 UI（用户是中文写作者）；文案简洁、错误信息具体化。
- 布局响应式：编辑器三栏可折叠（专注模式隐藏左右栏）。

## 【验收标准】

1. 现有全部功能不回退：6 个 AI 工具、创作向导、灵感套件、快照/版本历史、统计、设置 4 阶段+测试连接
2. 补齐 3 个缺失可视化组件（关系图/时间线/一致性）并接入编辑器左栏新 tab 或独立视图
3. `npx tsc --noEmit` 0 错误；`npx vitest run` 全绿（现有 45+ 用例不许删）；新增组件带测试
4. 全部颜色/间距走设计令牌；主题三态下均正常渲染
5. 编辑器 1300+ 行 page.tsx 拆分（面板组件化），单文件 <400 行

## 【风格基线】

写作工具的沉浸感优先于花哨：低饱和底色、清晰的正文层级、AI 输出与人工内容视觉可区分（如 AI 段落左侧细线）、生成中的进度反馈轻量不打断。参考：iA Writer 的克制、Notion 的块编辑密度、Obsidian 的关系图交互。
