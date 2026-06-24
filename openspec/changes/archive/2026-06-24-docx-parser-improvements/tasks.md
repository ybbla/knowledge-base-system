## 1. 重构 `_DocxParseState`（基础设施迁移）

- [x] 1.1 将 `_DocxParseState` 改为 `@dataclass` 继承 `_BaseParseState`
- [x] 1.2 新增字段：`_current_list_id`、`_tracked_assets`、`_link_urls`、`_image_asset_map`、`assets`
- [x] 1.3 新增方法：`track_asset(asset_id)`、`track_link_url(url)`、`consume_tracked_assets()`、`consume_link_urls()`
- [x] 1.4 修改 `add_paragraph`：消费 `_tracked_assets` → `el.asset_ids`，`_link_urls` → `el.metadata.link_urls`
- [x] 1.5 删除：显式 `__init__`、`_seq`、`_section_path`、`_next_seq`（从基类继承）、`_image_counter`

## 2. 导入公共工具，删除本地重复

- [x] 2.1 从 `parsers/utils.py` 导入：`guess_mime`、`is_video_url`、`is_attachment_url`、`normalize_text`、`VIDEO_URL_RE`、`HTTP_URL_RE`、`MIME_MAP`、`ATTACHMENT_EXTENSIONS`
- [x] 2.2 删除本地 `VIDEO_URL_RE` 正则（第 41-44 行）
- [x] 2.3 删除 `_extract_images` 中的本地 `mimetype_map` 字典
- [x] 2.4 新增 `_IMAGE_EXTENSIONS` 类属性常量

## 3. 非英文标题样式名支持

- [x] 3.1 新增类属性 `HEADING_KEYWORDS`（中/英/法/德/西/葡/意/日 8 种语言）
- [x] 3.2 新增 `_detect_heading_level(style_name, docx) -> int | None` 方法
- [x] 3.3 修改 `_process_paragraph`：用 `_detect_heading_level()` 替换两阶段检测
- [x] 3.4 增加 `is_list` 保护：列表样式强制 `heading_match = None`

## 4. 段落中内联图片（`w:drawing`）处理

- [x] 4.1 新增 `_extract_drawing_rIds(p_el) -> list[str]`：提取 `w:drawing` → `a:blip` → `r:embed`
- [x] 4.2 新增 `_resolve_image_asset(rId, docx, state) -> Asset | None`：通过 rId 在 asset map 中查找
- [x] 4.3 修改 `_process_paragraph` 文本提取：从全量 `p_el.iter()` 改为按直接子元素遍历
- [x] 4.4 对 `w:r` 子元素：先检查 `w:drawing` → 提取 rId → 解析 Asset → `track_asset`，再提取 `w:t` 文本
- [x] 4.5 图片在文本中用 `[图片: filename]` 占位
- [x] 4.6 修改空段落跳过逻辑：有 drawing/hyperlink 但无文本的段落仍创建元素

## 5. 段落中超链接（`w:hyperlink`）处理

- [x] 5.1 遍历 `w:p` 的直接子元素时处理 `w:hyperlink`
- [x] 5.2 提取显示文字：遍历 `w:hyperlink` 内部所有 `w:t` 节点
- [x] 5.3 提取目标 URL：通过 `r:id` → `docx.part.rels` → `rel.target_ref`
- [x] 5.4 新增 `_classify_link_url(url) -> AssetType | None`（与 MarkdownParser 相同逻辑）
- [x] 5.5 文件/附件链接 → 创建 Asset，文本只保留显示文字，`track_asset`
- [x] 5.6 视频链接 → 创建 Asset，文本只保留显示文字，`track_asset`
- [x] 5.7 图片链接 → 创建 Asset，文本只保留显示文字，`track_asset`
- [x] 5.8 普通网页链接 → URL 写入 `metadata.link_urls`，文本保留显示文字

## 6. 图片预提取重构

- [x] 6.1 将 `_extract_images` 改为 `_build_image_asset_map(doc, state)`
- [x] 6.2 从 zip 提取 `word/media/*` → 创建 Asset → 存入 `state._image_asset_map` 和 `state.assets`
- [x] 6.3 不再创建独立的 image 类型 ParsedElement
- [x] 6.4 使用 `utils.guess_mime` 代替本地 MIME 字典

## 7. 表格单元格图片和超链接处理

- [x] 7.1 修改 `_process_table` 单元格提取：`w:tc` 的直接子元素是 `w:p`（不是 `w:r`/`w:hyperlink`），遍历每个 `w:p`，复用段落子元素遍历模式
- [x] 7.2 对每个 `w:p` 内的 `w:r`：提取 `w:drawing` → `_resolve_image_asset()` → 收集到 `cell_asset_ids`
- [x] 7.3 对每个 `w:p` 内的 `w:hyperlink`：提取显示文字 + URL → 调用 `_classify_link_url()` 分类处理 → asset_ids 收集到 `cell_asset_ids`
- [x] 7.4 提取 `w:p` 内的 `w:t` 文本拼接 cell 文本，多个 `w:p` 用换行符分隔
- [x] 7.5 单元格存储从 `str` 改为 `(text: str, asset_ids: list[str])` 元组
- [x] 7.6 更新 `vertical_merges` 字典：值类型从 `str` 改为 `tuple[str, list[str]]`
- [x] 7.7 更新 `structured_data`：每个 cell 的 `asset_ids` 从实际提取填充，表格级汇总去重

## 8. 视频提取更新

- [x] 8.1 修改 `_extract_videos`：使用 `utils.VIDEO_URL_RE` 和 `utils.guess_mime`
- [x] 8.2 不再创建独立的 video 类型 ParsedElement
- [x] 8.3 Asset 存入 `state.assets`

## 9. 整合 `parse()` 入口

- [x] 9.1 新流程：`_build_image_asset_map` → body 遍历 → `flush_elements` → `_extract_videos` → `_link_assets_to_elements` → `compute_hash`
- [x] 9.2 新增 `_link_assets_to_elements(elements, assets)`（与 MarkdownParser 相同模式）
- [x] 9.3 返回 `ParseResult(doc=doc, elements=elements, assets=state.assets)`

## 10. 清理旧代码 + 更新测试

- [x] 10.1 删除 `_extract_images` 方法（替换为 `_build_image_asset_map`）
- [x] 10.2 删除本地 `VIDEO_URL_RE`
- [x] 10.3 删除本地 MIME 字典
- [x] 10.4 新增测试：`test_heading_chinese` — 中文"标题 1"样式正确识别
- [x] 10.5 新增测试：`test_heading_french` — 法文"Titre 1"样式正确识别
- [x] 10.6 新增测试：`test_paragraph_with_image` — 段落中内联图片关联到 `asset_ids`，文本含 `[图片: xxx]`
- [x] 10.7 新增测试：`test_paragraph_with_hyperlink` — 段落中普通网页超链接 URL 写入 `metadata.link_urls`
- [x] 10.8 新增测试：`test_paragraph_with_attachment_link` — 文件/附件链接创建 Asset，段落文本只保留显示文字
- [x] 10.9 新增测试：`test_paragraph_with_video_link` — 视频链接创建 Asset 并关联到段落
- [x] 10.10 新增测试：`test_table_cell_with_image` — 表格单元格图片关联到 `structured_data` 的 cell `asset_ids`
- [x] 10.11 新增测试：`test_table_cell_with_hyperlink` — 表格单元格超链接正确处理
- [x] 10.12 新增测试：`test_merged_cell_with_asset` — gridSpan/vMerge 合并单元格正确传递 asset_ids
- [x] 10.13 新增测试：`test_image_only_paragraph` — 纯图片段落（无文本）仍创建元素
- [x] 10.14 新增测试：`test_asset_source_element_backfill` — `_link_assets_to_elements` 正确回填
- [x] 10.15 适配已有测试：`test_extract_embedded_image_from_raw_content` — 图片不再创建独立 image 元素，改为关联到段落
- [x] 10.16 运行全量回归测试：`pytest tests/ -v`
