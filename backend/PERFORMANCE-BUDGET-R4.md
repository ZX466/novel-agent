# 性能预算报告：Round 4（F1 对话助手 / F6 统计看板 / 编辑器流畅度）

> **执行人**：Pi（性能域 Agent）
> **日期**：2026-08-17
> **任务来源**：Claude 主协调 Round 4 分配（P2）
> **协作**：与 Claude（前端/体验）就编辑器流畅度给出性能建议；看板/导出接口由 kilo 实现，本报告给出性能预算前提
> **评审 Agent**：cline

---

## 一、背景与范围

Round 4 新增功能：
- **F1 AI 对话助手**（多轮消息，可注入章节/大纲上下文）
- **F6 写作统计看板**（字数曲线 / 连续天数 / 今日目标）
- **写作体验完善**（编辑器大文档输入流畅度等）

本报告聚焦三块性能预算：多轮对话 TTFT、统计看板大文档量查询、编辑器 >100KB 输入流畅度。

---

## 二、F1 多轮对话性能预算

### 2.1 现状（代码审计）

`frontend/src/components/Chat.tsx` 使用 `@ai-sdk/react` 的 `useChat`：
- 前端保留多轮消息历史，`sendMessage({text})` 把**全部历史**发给后端（AI SDK 默认行为）
- 后端 `backend/app/api/chat.py` 的 `_extract_topic()` **只取最后一条 user 消息**作为 pipeline topic
- consumer 侧：历史消息不进入 LLM 调用（draft 只收到 topic + RAG 检索结果）

**结论：后端无上下文累积重放** —— TTFT 与"轮数"弱相关（这是已存在的合理设计，避免了上下文膨胀导致的 TTFT 线性增长）。

### 2.2 真正影响 TTFT 的因素

| 因子 | 影响 | 预算 |
|------|------|------|
| topic 长度（多轮讨论中问题变长） | embedding 时延线性、draft prompt 变长 | +0.1~0.3s / 每增 2000 字 |
| RAG 检索（4 集合，本地实测） | 并发 50.8ms + embed RTT（100-500ms） | 0.2-0.6s |
| draft TTFT | 模型首 token 时延 | 0.3-0.8s |
| **合计（并发后）** | — | **0.65-1.7s** |

### 2.3 F1 章节/大纲上下文注入的预算约束（关键建议）

F1 需求"章节/大纲上下文注入"如果**在每次请求中注入历史章节全文**，会显著膨胀 draft 的 system prompt：
- 估算：每章 ~3000 字，注入 10 章 ≈ 3 万字 ≈ ~40k tokens（中文）→ draft TTFT 可能 +2-5s
- **预算建议**：
  1. **上下文注入用 RAG 检索结果**（top 3-5 条，`_format_retrieval_context` 已限 8000 字符 ✅），**不要**注入全章节
  2. 用户可选的"带入上下文"开关，默认关
  3. 注入内容截断上限：**字符预算 ≤ 8000**（已有 `[:8000]` 限制，保持一致）
  4. 多轮对话的**轮次上限**建议（如最近 N=20 条），防 UI 层历史无限膨胀的内存占用

### 2.4 TTFT 预算表（目标）

| 场景 | 目标 TTFT | 依据 |
|------|----------|------|
| 首轮简单提问 | ≤ 1.0s | RAG 并发 + draft 快模型 |
| 多轮追问（topic 增长） | ≤ 1.5s | topic 未超 8000 字符 |
| 带上下文注入（RAG） | ≤ 2.0s | embed + 检索 + draft |
| 大 topic（>8000 字符） | 触发截断/降级 | 超出预算保护 |

---

## 三、F6 统计看板性能预算

### 3.1 数据可用性（已确认）

`documents` 表已具备看板所需列：`word_count`、`created_at`、`updated_at`、`status`、`category`、`doc_type`（`app/models/document.py`）。**无需新列**。

### 3.2 性能建议（供 kilo 实现参考）

**看板三类查询**：
1. **字数曲线**（按天聚合字数）→ 需要时间粒度数据。当前 `word_count` 是**瞬时值**（每次保存覆盖），无历史轨迹。**建议**：
   - 若 kilo 实现"字数曲线"，需 `evaluations` 表旁路或新聚合表/物化视图
   - **查询预算**：单文档 365 天的字迹曲线应 ≤ 50ms（按天聚合索引）
2. **连续天数**（写作活跃日）→ 基于 `updated_at` 的分组查询
3. **今日目标** → 当日 `updated_at` + word_count 增量

**查询模式预算**：
| 查询 | 数据量 | 预算 | 索引要求 |
|------|--------|------|---------|
| 单文档字数曲线 | ~365 行/年 | ≤ 50ms | `(novel_id, updated_at)` 复合索引 |
| 全库活跃天数 | 1000 文档 | ≤ 200ms | `status` + `updated_at` |
| 列表 + 计数 | 1000 文档 | ≤ 100ms | 既有 `updated_at` 索引 |

**大文档量（>10k 文档）注意**：
- 聚合查询避免 `SELECT *` 拉大文本列（`content_text`/`content_html`）——**必须只选聚合列**
- 建议窗口聚合函数（`date_trunc('day', ...)`) + `GROUP BY`，pg 原生支持
- 若看板要跨文档统计，考虑**每晚物化视图**（`MATERIALIZED VIEW`）而非实时聚合

---

## 四、编辑器大文档（>100KB）输入流畅度建议

### 4.1 现状（代码审计）

`frontend/src/components/Editor.tsx`：
- Tiptap（ProseMirror）编辑器，`EditorContent` 渲染
- **`EditorStats` 每次渲染都执行**：
  ```js
  const text = editor.getText();                              // 全文档序列化
  const cjk = (text.match(/[\u4e00-\u9fff\u3400-\u4dbf]/g) || []).length;  // 全文正
  const latin = (text.match(/[a-zA-Z]+/g) || []).length;      // 全文正则
  ```
- **问题**：`EditorStats` 在父组件每次渲染都重算（`getText()` + 3 次全文正则），>100KB（~5-8 万字）时每次打字触发一次全量扫描
- `use-documents.ts`：保存是**手动触发**（无自动防抖），良好——但保存时后端 `_compute_word_count` 全量正则会重算

### 4.2 建议（与 Claude 协作项）

| # | 建议 | 收益 | 复杂度 |
|---|------|------|--------|
| 1 | **`EditorStats` 用 `useMemo` + 防抖**：`useMemo(() => computeStats(editor.getText()), [dirty, wordCountCache])`，或改用 Tiptap `onUpdate` 事件 + 300ms 防抖重算 | 打字时不再每次全量扫描；>100KB 文档流畅度↑↑ | 低 |
| 2 | **`editor.getText()` 的结果**只缓存摘要（不缓存全文）：`getText()` 本身 O(n)，防抖可避免高频重复 | 同上 | 低 |
| 3 | **后端 `_compute_word_count` 增量**：PATCH 时如果 content 前 100 字符不变且仅追加，可增量计算（报告建议项，P3） | 保存大文档时后端少一次全文正则 | 中 |
| 4 | **ProseMirror 大文档优化**：确认 Tiptap extension 无高开销插件；`EditorContent` 不需要在非编辑时渲染 → 用 `React.memo` | 减少无效重渲染 | 低 |
| 5 | 编辑器**只读预览模式**（大文档查看时不走完整编辑链） | 查看 100KB+ 文档流畅 | 中 |

### 4.3 预估基准
- >100KB 文档：EditorStats 防抖后，打字延迟从 ~50-150ms/keystroke（全量正则）降至 <16ms（60fps 流畅线）
- 保存时 word_count 计算：增量计算可省 60-80% 后端正则时间

---

## 五、结论汇总

| 子项 | 现状 | 预算/建议 | 责任 |
|------|------|----------|------|
| F1 多轮 TTFT | 后端不重放历史（优）；RAG 并发 50.8ms | 首轮 ≤1.0s / 追问 ≤1.5s；上下文用 RAG 限 8000 字符 | Pi 已评估，Claude/kilo 落实 |
| F6 统计看板 | 无路由（kilo 待实现）；列已具备 | 单查询 ≤50-200ms；聚合只选标量列；字数曲线需聚合方案 | kilo 实现，Pi 给预算 |
| 编辑器 >100KB | EditorStats 全量正则每次渲染 | useMemo+防抖 → <16ms；增量 word_count | Claude（前端）落实 |

**关键性能红线**：
1. 上下文注入字符预算 ≤ 8000（防止 TTFT 超预算）
2. 看板聚合查询禁拉大文本列（防内存/IO 放大）
3. 编辑器统计重算必须防抖（打字流畅度）

---

## 六、基准验证方案（后续可执行）

1. **多轮对话 TTFT**：在本地起后端 + mock LLM，发 5 轮递增上下文对话，测每轮首 token 到达时间（应稳定）
2. **看板查询**：注入 10k 文档模拟数据，测三条聚合 SQL 的 EXPLAIN ANALYZE
3. **编辑器**：Chrome DevTools Performance 录 100KB 文档打字 10 秒，对比防抖前后

*Round 4 性能预算报告结束。数据源：代码审计 + 第三轮真实 DB 基准（RAG 并发 50.8ms）。*
