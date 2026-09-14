# 灵感套件四项修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 总纲全局模式改为居中弹层;灵感套件基于作品上下文生成;大纲提取补关系线;灵感套件不再写大纲。

**Architecture:** 四项独立修复。① OutlinePanel 内联全屏改模态弹层(对齐 CreativeKitDialog 模式)。②③④ 灵感套件链路:前端 buildKitPrompt 注入作品上下文、extract 管线加 relationships 第四类、后端 apply_creative_kit 删 outline 合并。前端为主,后端两处小改。

**Tech Stack:** Next.js 14 / React / vitest / FastAPI / pytest (uv)

**Spec:** 本轮对话设计(2026-09-13 用户确认):全局=居中弹层;灵感套件生成须基于作品现状;大纲提取要有关系线;灵感套件不得修改大纲(预览标注"仅供参考")。

## Global Constraints

- 测试命令:后端 `uv run pytest`(backend 目录);前端 `npx vitest run`(frontend 目录);类型 `npx tsc --noEmit`
- 样式对齐现有弹层惯例:`fixed inset-0 z-50` + 遮罩 `rgba(0,0,0,0.4)` + `var(--surface)` 面板(CreativeKitDialog.tsx:223-233 为范本)
- 保留 R10-⑨ 既有契约:润色回调签名 `onAiPolish(onDone, onError)`;blur 自动保存;polishError 显示
- 后端 outline 合并删除后,`CreativeKitApplyResponse.outline_applied` 字段保留(恒 False,向后兼容 schema)——前端不再显示"主线大纲"于已应用文案
- extract 提示词改动只动 system_content(nodes.py:504-512),JSON 输出格式新增 relationships 数组
- 关系导入走现成 `POST /v1/documents/{id}/characters/relationships/import`(importRelationships,按名字解析,未知端点服务端跳过)
- 提交:conventional commits,尾行 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

### Task 1: 总纲全局模式 → 居中弹层

**Files:**
- Modify: `frontend/src/components/OutlinePanel.tsx`
- Test: `frontend/src/components/__tests__/OutlinePanel.test.tsx`(已存在,改断言)

**Interfaces:**
- Consumes: 现有 props 不变(onAiPolish/onSaveOutline 等);CreativeKitDialog 弹层样式范本(z-50/遮罩/面板)
- Produces: outlineFullscreen 状态语义变为"弹层开关";弹层含编辑区+工具按钮行(提取/润色/全局切换/编辑保存)

- [ ] **Step 1: 改测试(RED)** — OutlinePanel.test.tsx 第二个用例改为:点全局后 textarea 出现在 `role="dialog"` 容器内、container 有 `fixed inset-0 z-50` class、textarea 仍带 flex-1;加"点遮罩关闭"用例

```tsx
it("全局模式 opens a centered modal dialog", () => {
  setup();
  fireEvent.click(screen.getByText("编辑"));
  fireEvent.click(screen.getByTitle(/全局模式/));
  const dialog = screen.getByRole("dialog");
  expect(dialog.className).toContain("fixed");
  expect(dialog.className).toContain("z-50");
  const textarea = screen.getByPlaceholderText(/在此编写或粘贴小说大纲/);
  expect(textarea).toHaveClass("flex-1");
  // Escape via overlay close
  fireEvent.click(screen.getByLabelText("退出全局模式"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: 跑测试确认 RED**(`npx vitest run src/components/__tests__/OutlinePanel.test.tsx`)
- [ ] **Step 3: 实现(GREEN)** — OutlinePanel:outlineFullscreen 时渲染 `fixed inset-0 z-50 flex items-center justify-center` 弹层;遮罩 onClick 退出;面板 `w-[92vw] max-w-[1080px] h-[86vh] flex flex-col rounded-lg border shadow-2xl`,header 行(总纲标题+工具按钮组+关闭按钮),body flex-1 放编辑/预览态;删内联伸展旧逻辑;非全屏分支恢复 max-height 布局;章节列表在弹层打开时无需隐藏(弹层覆盖)
- [ ] **Step 4: 跑测试确认 GREEN + tsc PASS**
- [ ] **Step 5: Commit** `fix: 总纲全局模式改居中弹层(样式对齐 CreativeKitDialog)`

### Task 2: 灵感套件注入作品上下文

**Files:**
- Modify: `frontend/src/components/CreativeKitDialog.tsx`
- Test: `frontend/src/components/__tests__/CreativeKitDialog.test.tsx`(新建)

**Interfaces:**
- Consumes: `getDocument`(lib/documents)、`listCharacters`(lib/characters)、`listWorldSettings`(lib/world-settings,先确认导出名;若无则 fetch `/world-settings` 列表端点)、props.docId
- Produces: buildKitPrompt 增加第 5 参 `context: { title, description, outline, castSummaries, worldTitles }`(全 string);生成前并行拉取

- [ ] **Step 1: 写失败测试(RED)** — mock lib 层,断言:生成时 getDocument/listCharacters 被调用;prompt 文本包含标题/简介/人物定位摘要/世界观标题;outline 截 3000 字;无 doc 时(全部失败)prompt 仍生成且 context 为空串

```tsx
// 关键断言形态(useChat mock sendMessage 捕获 text):
expect(sent.text).toContain("作品现状");
expect(sent.text).toContain("低语者");
expect(sent.text).toContain("陈默(主角)");
```

- [ ] **Step 2: 跑测试确认 RED**
- [ ] **Step 3: 实现(GREEN)** — buildKitPrompt 加 context 参数拼「作品现状」块(标题/简介/已有角色列表 name+role/世界观标题/现有大纲前 3000 字,空值省略);handleGenerate 改 async 并行拉取(Promise.all,单项 catch 空),注入后 sendMessage;指令行改为"基于作品现状生成与当前故事一致、延续既有设定的灵感套件,世界观与人物不得与已有设定冲突,大纲作为主线参考可扩写但不得推翻既有走向"
- [ ] **Step 4: GREEN + tsc PASS**
- [ ] **Step 5: Commit** `fix: 灵感套件生成注入作品上下文(标题/简介/角色/世界观/大纲)`

### Task 3: 大纲提取补关系线

**Files:**
- Modify: `backend/app/pipeline/nodes.py`(extract system_content,~504-512)
- Modify: `frontend/src/lib/types.ts`(ExtractEntitiesResult/ExtractedRelationship)
- Modify: `frontend/src/lib/extract-entities.ts`(parseExtractJson)
- Modify: `frontend/src/lib/entity-extraction.ts`(extractAndCreateEntities)
- Test: `backend/tests/test_pipeline_think_filter.py` 或新文件 `backend/tests/test_extract_relationships.py`;`frontend/src/lib/__tests__/entity-extraction.test.ts`(若无则新建)

**Interfaces:**
- Consumes: `importRelationships(docId, items)`(lib/character-relationships,RelationshipImportItem{subject_name,object_name,relation_type?,description?,strength?})
- Produces: ExtractEntitiesResult.relationships?: ExtractedRelationship[];ExtractionOutcome.relationships 计数;formatExtractionSummary 含"N 条关系"

- [ ] **Step 1: 后端 RED** — 新测试:patch nodes.llm_draft 捕获 messages,task_type=extract 时 system_content 含「relationships」与「relation_type」字样

```python
@pytest.mark.asyncio
async def test_extract_system_prompt_asks_for_relationships() -> None:
    state = {"topic": "大纲", "task_type": "extract"}
    captured = {}
    def _capture(messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return _as_async_iter([_chunk('{"characters":[],"world_settings":[],"plot_events":[]}')])
    with patch.object(nodes, "llm_draft", AsyncMock(side_effect=_capture)):
        await nodes.draft_node(state)
    assert "relationships" in captured["system"]
    assert "relation_type" in captured["system"]
```

- [ ] **Step 2: RED 确认 → 实现(nodes.py extract 分支 JSON 格式说明加 relationships 字段) → GREEN**
- [ ] **Step 3: 前端 RED** — entity-extraction 测试:mock extractEntitiesFromOutline 返回含 relationships([{subject_name:"陈默",object_name:"苏晚晴",relation_type:"搭档",strength:8}])与 characters,mock importRelationships 断言被调用且返回计数进入 outcome;formatExtractionSummary 断言含「2 条关系」

```ts
const outcome = await extractAndCreateEntities(1, "大纲");
expect(importRelationships).toHaveBeenCalledWith(1, [
  { subject_name: "陈默", object_name: "苏晚晴", relation_type: "搭档", strength: 8 },
]);
expect(outcome.relationships).toBe(1);
expect(formatExtractionSummary(outcome)).toContain("1 条关系");
```

- [ ] **Step 4: RED 确认 → 实现(types 加 ExtractedRelationship{subject_name,object_name,relation_type?,description?,strength?}+result.relationships?;parseExtractJson 透传;extractAndCreateEntities 在 charResults settle 后调 importRelationships(entities.relationships 非空时),计数进 outcome;summary 加关系段) → GREEN**
- [ ] **Step 5: Commit** `feat: 大纲实体提取补人物关系线(import 复用名字解析)`

### Task 4: 灵感套件不再写大纲

**Files:**
- Modify: `backend/app/services/creative_kit.py`(删 outline 合并块 190-196)
- Modify: `backend/app/schemas/creative_kit.py`(CreativeKitApplyRequest.outline 改注释"已废弃,忽略";字段保留默认 "" 以兼容旧客户端)
- Modify: `backend/tests/test_creative_kit.py`(改 test_outline_merges_only_own_keys → 断言不写入)
- Modify: `frontend/src/lib/creative-kit.ts`(applyCreativeKit 请求不再发 outline;注释)
- Modify: `frontend/src/components/CreativeKitDialog.tsx`(handleApply 不发 outline;主线大纲预览标注"仅供参考,不会写入作品")
- Test: 上述后端测试文件

**Interfaces:**
- Consumes: 现有 mock_session 测试基建
- Produces: outline_applied 恒 False;outline 键不再被 apply 触碰

- [ ] **Step 1: 后端 RED** — 改 test_outline_merges_only_own_keys:断言 doc.metadata_json["outline"] 保持"旧大纲"、version 不变、res.outline_applied is False

```python
res = await apply_creative_kit(mock_session, 7, CreativeKitApplyRequest(outline="全新大纲"))
assert doc.metadata_json["outline"] == "旧大纲"   # untouched
assert doc.version == 3
assert res.outline_applied is False
```

- [ ] **Step 2: RED → 实现(删 190-196 合并块,outline_applied=False) → GREEN;顺跑 test_creative_kit_api.py**
- [ ] **Step 3: 前端实现** — applyCreativeKit body 去掉 outline(CreativeKitApplyRequest.outline 标可选 deprecated);CreativeKitDialog handleApply 不传 outline;预览区"主线大纲"标题旁加灰字"仅供参考,不会写入作品"
- [ ] **Step 4: vitest + tsc PASS(creative-kit.test.ts 若断言请求体含 outline 需同步改)**
- [ ] **Step 5: Commit** `fix: 灵感套件应用不再覆盖大纲(预览仅供参考)`

---

## Self-Review

- 覆盖:全屏弹层(Task1)/上下文注入(Task2)/关系线(Task3)/不写大纲(Task4)——四项需求全有对应任务 ✓
- 占位符:无 TBD;Task2 worldSettings 列表导出名标注"先确认"是实施动作非占位 ✓
- 类型一致:RelationshipImportItem 字段名 subject_name/object_name 与 lib 现有一致(已核对 character-relationships.ts:57-63);KitRelationship(subject/object)与 ExtractedRelationship(subject_name/object_name)是不同层,import 转换在 entity-extraction 做映射 ✓
- 风险:Task2 的 useChat mock 需要摸 CreativeKitDialog 现有测试基建(无既有测试文件,新建时用 vi.mock("@ai-sdk/react"))
