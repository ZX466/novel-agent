# 卡片 04｜导出投稿

> 目标：把作品导出为 md / txt / epub，给投稿或本地存档。

## 操作步骤

1. **打开导出**
   - 作品页 → “导出”（受保护端点，需 `X-API-Key`）。

2. **选择格式**
   - `GET /v1/documents/{doc_id}/export?format=md|txt|epub`
   - `md`：Markdown（章节分隔 + 元数据，适合再加工）
   - `txt`：纯文本（适合投稿站直接粘贴）
   - `epub`：标准 EPUB 3（标准库 zip 生成，无需额外安装，中文标题已做 RFC 5987 编码）

3. **浏览器下载**
   - 响应为文件下载；文件名含作品标题（已安全转义）。

## 一行验证

> 下载 `.epub` 后可用 epubcheck 或阅读器打开，章节顺序与作品页一致。

## 常见坑

- **中文文件名乱码**：导出接口已用 `Content-Disposition`（RFC 5987）处理；仍乱码时检查浏览器/下载工具是否按 RFC 5987 解析。
- **章节顺序不对**：按 `chapter_index` 排序导出；确认章节 `chapter_index` 无重复/空洞。
- **epub 校验告警**：epubcheck 对空 `metadata` 或缺失 `nav` 会告警；本实现为最小 EPUB，功能以阅读器兼容为准。