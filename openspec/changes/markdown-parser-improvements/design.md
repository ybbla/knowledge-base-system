## Context

MarkdownParser 已能正确解析标题、段落、列表、表格和代码块，但 blockquote 和链接两种语义元素被忽略，表格内的资源也未关联。同时，该解析器仍使用内联的 `VIDEO_URL_RE` 等重复代码。

依赖：`parser-common-infra`（提供 `utils.py` 和 `_BaseParseState`）和 `decouple-content-from-parser`（已删除 `_read_content`，接口改为 `parse(doc, content)`）已完成。

## Goals / Non-Goals

**Goals:**
- 迁移到公共基础设施（utils + _BaseParseState）
- blockquote 内容保留并通过 metadata 标记
- 段落内链接 URL 按类型创建 Asset（附件/视频/图片）或写入 metadata
- 表格单元格内资源关联到 `cells[].asset_ids`

**Non-Goals:**
- 不新增 `ElementType.blockquote`（待后续独立 change）
- 不修改 `_process_token` 的核心分发逻辑

## Decisions

### 1. blockquote 通过 metadata 标记而非新 ElementType

在 `_ParseState` 中新增 `in_blockquote: bool`，`blockquote_open` 时设为 True，`blockquote_close` 时设为 False。段落生成时若 `in_blockquote` 为 True，设置 `metadata["blockquote"] = True`。

### 2. 链接 URL 在 `_process_token` 的 inline 分支处理

在已有的 `image` 子 token 处理旁新增 `link` 分支：
- 提取 `href`（从 `child.attrs` 取）
- URL 匹配 `VIDEO_URL_RE` / 图片扩展名 / `ATTACHMENT_EXTENSIONS` → 创建 Asset + `add_asset_id()`
- 普通网页 URL → 追加到 `_link_urls`，段落关闭时写入 `metadata.link_urls`

### 3. 表格单元格：`_current_row` 类型升级

`_current_row` 从 `list[str]` 改为 `list[tuple[str, list[str]]]`——每格存 `(文本, asset_ids)`。`close_table()` 从中读出每格的 asset_ids 填入 `structured_data.table.rows[].cells[].asset_ids`，同时汇总到表格级 `asset_ids`。

### 4. `_tracked_assets` 为段落和表格共用

图片/链接创建的 Asset 统一走 `add_asset_id()` → `_tracked_assets`。段落关闭时 `add_paragraph()` 消费，表格单元格 inline 结束时从 `_current_row` 消费。

## Risks / Trade-offs

- **[风险] blockquote metadata 在下游被忽略**：`SemanticExtractor` 可能不检查 `metadata.blockquote`。→ **缓解**：metadata 至少保留了信息，后续可独立改造语义层利用该标记
- **[风险] 表格 inline 顺序**：`inline` token 先经 `_render_inline_text` 提取文本，再遍历子 token 处理资源——顺序保证文本和 asset_ids 对齐
