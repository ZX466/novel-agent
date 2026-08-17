# EPUB 导出依赖评估（F3 前置输入）

> 评估人: cline（依赖/配置/文档域）· 2026-08-17
> 服务对象: kilo（F3 导出端点实现）· 决策人: Claude 主协调
> 任务来源: Round 4 `[P2] 依赖评估：EPUB 生成所需 Python 库可行性 + 加入 pyproject 的建议`

## 结论（TL;DR）

**推荐方案 A：Python 标准库 `zipfile` 手写 EPUB 3 最小生成器，不新增任何依赖。**

小说导出是"线性章节 + 目录 + 元数据"的简单结构，标准库 150 行左右即可生成合法 EPUB 3；与 kilo 任务描述中"EPUB 需生成 zip 容器"的预期一致，且保持项目最小依赖的姿态（参考 `litellm<1.91` 硬 pin 的先例）。pyproject **无需改动**。

## 候选方案对比

| 方案 | 新增依赖 | 平台风险 | 维护性 | 适配 F3 | 结论 |
|------|---------|---------|--------|---------|------|
| A. stdlib `zipfile` 手写 | **0** | 无（纯标准库） | 自维护 ~150 行 | 完全够用 | ✅ **推荐** |
| B. `ebooklib>=0.18` | ebooklib + lxml + six（传递） | lxml 二进制 wheel 三平台均可用 | 上游 2022 年起维护停滞 | 够用且更省样板 | 🟡 备选 |
| C. `weasyprint` | 重（需 Cairo/Pango/GDK 原生库） | Windows 需 GTK 运行时；Docker 需装系统包 | — | ❌ **是 HTML→PDF 工具，不产出 EPUB** | ❌ 排除 |
| D. `pypandoc`（外部 pandoc 二进制） | 系统级二进制 | 部署需单独装 pandoc | — | 杀鸡用牛刀 | ❌ 排除 |

### 方案 A 细节（推荐）

EPUB 3 本质是一个 ZIP 容器，必需结构：

```
mimetype            ← 必须是第一个条目，ZIP_STORED（不压缩），内容固定 "application/epub+zip"
META-INF/container.xml
OEBPS/content.opf   ← 元数据 + manifest + spine
OEBPS/nav.xhtml     ← EPUB 3 目录（toc）
OEBPS/chapter-N.xhtml
OEBPS/style.css
```

**关键坑（实现时必须注意）**：
1. `mimetype` 必须为 ZIP 中**第一个**条目，且 `compress_type=ZIP_STORED`、**不能有 extra field** —— 用 `zipfile.ZipInfo("mimetype")` + `zf.writestr(zinfo, "application/epub+zip")`，不要直接 `zf.write()`。
2. 章节正文从 `content_text` 转义为 XHTML（`<pre>` 包裹或分段 `<p>`），题目/标题做 XML 转义。
3. 文件名建议 `<title>.epub`（ sanitized），响应头 `Content-Disposition: attachment; filename*=UTF-8''...`（RFC 5987，中文标题必须用 filename* 形式）。
4. 验证工具：`epubcheck`（Java）可后续按需加进 CI，非本轮必需。

### 方案 B 细节（备选）

若后续需要富特性（封面图、内嵌字体、EPUB 2 兼容、复杂 spine），再引入：

```toml
# backend/pyproject.toml dependencies 追加（本轮不加）
"ebooklib>=0.18,<0.19",   # 上游维护停滞，先锁小版本
```

- 传递依赖 lxml（wheel 齐全）+ six；`uv lock` 会自动处理。
- ebooklib 自动处理 mimetype 首条目等容器细节，省样板但失去控制力。

### 方案 C 排除理由（weasyprint）

任务原文提到的 weasyprint **不是 EPUB 生成器**——它是 HTML→PDF 渲染器，输出 PDF。且其依赖链（cffi + Pango/Cairo/GDK-PixBuf 原生库）在 Windows 开发机与生产 Docker 镜像都显著抬高部署成本。若未来 F3 扩展 PDF 导出，届时再单独评估（届时也建议先考虑无头浏览器/reportlab 等更轻路径）。

## 对 pyproject 的建议

- **本轮（F3 md/txt/epub）：不改动 `backend/pyproject.toml`**。
- `requirements.txt` 与 pyproject 保持同步原则不变（README §目录 已注明 pyproject 为唯一权威）。
- 若 kilo 评估后倾向方案 B，需在分支上同时更新 pyproject + `uv lock` + requirements.txt 三处并过 `uv sync` 验证。
