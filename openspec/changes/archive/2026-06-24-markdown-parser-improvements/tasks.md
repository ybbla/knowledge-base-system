## 1. 基础设施迁移

- [x] 1.1 删除本地 `VIDEO_URL_RE` 和 `_guess_mime()`，导入 `utils` 模块
- [x] 1.2 `_ParseState` 继承 `_BaseParseState`，移除重复字段（doc_id, doc_version, elements, _seq, _section_path, _next_seq()）

## 2. blockquote 语义保留

- [x] 2.1 `_ParseState` 新增 `in_blockquote: bool = False` 字段
- [x] 2.2 `blockquote_open` 设置 `state.in_blockquote = True`
- [x] 2.3 `blockquote_close` 设置 `state.in_blockquote = False`
- [x] 2.4 `add_paragraph()` 中：若 `in_blockquote` 为 True，设置 `metadata["blockquote"] = True`

## 3. 段落内链接 URL 提取

- [x] 3.1 `_ParseState` 新增 `_link_urls: list[str]` 字段
- [x] 3.2 `_process_token` `inline` 分支：`link` 子 token 提取 `href`
- [x] 3.3 若 URL 匹配 `VIDEO_URL_RE` / 图片扩展名 / `ATTACHMENT_EXTENSIONS` → 创建 Asset + `add_asset_id`
- [x] 3.4 普通网页 URL → 追加到 `_link_urls`
- [x] 3.5 `add_paragraph()` 中：若 `_link_urls` 非空，写入 `metadata["link_urls"]`，然后清空

## 4. 表格单元格内资源关联

- [x] 4.1 `_current_row` 类型从 `list[str]` 改为 `list[tuple[str, list[str]]]`（每格存 (文本, asset_ids)）
- [x] 4.2 `inline` 处理中表格单元格分支：从 `_current_row.append(inline_text)` 改为 `_current_row.append((inline_text, list(state._tracked_assets)))`，然后清 `_tracked_assets`
- [x] 4.3 表格内 `image` / `link` 子 token 的 Asset 创建与段落内复用同一逻辑
- [x] 4.4 `close_table()` 从 `_current_row` 读出每格的 `(text, asset_ids)`，填入 `structured_data.table.rows[].cells[].asset_ids`

## 5. 收尾

- [x] 5.1 运行 `pytest tests/test_markdown_ingest.py -v` 确认无回归
- [x] 5.2 补充 blockquote、链接 URL、表格资源关联的测试用例
