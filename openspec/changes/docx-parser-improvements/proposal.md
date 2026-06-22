## Why

当前 `DocxParser` 存在以下缺失功能：

1. **段落内联图片未关联**：`w:drawing` 元素被忽略，图片通过 `_extract_images` 全量提取为独立元素，未关联到所在段落
2. **段落超链接未处理**：`w:hyperlink` 元素被忽略，只提取了其中的纯文本
3. **表格内图片/链接未处理**：表格单元格内不提取图片和超链接，`asset_ids` 始终为空
4. **标题仅支持英文样式名**：中文"标题 1"、法文"Titre 1"等无法识别
5. **使用内联重复代码**：本地有 `VIDEO_URL_RE`、MIME 映射等，应迁移到 `parsers/utils.py`

同时合并已有的 `openspec/changes/docx-parser-improvements/` 计划（非英文标题 + 基础设施迁移）。

## What Changes

- **基础设施迁移**：`_DocxParseState` 改为 `@dataclass` 继承 `_BaseParseState`，新增资源跟踪字段（`_tracked_assets`、`_link_urls`、`_image_asset_map`），删除显式 `__init__` 和重复字段
- **公共工具导入**：从 `parsers/utils.py` 导入 `guess_mime`、`is_video_url`、`is_attachment_url`、`normalize_text`、`VIDEO_URL_RE` 等，删除本地重复代码
- **非英文标题样式名支持**：新增 `HEADING_KEYWORDS` 多语言关键词集合（中/英/法/德/西/葡/意/日），新增 `_detect_heading_level()` 方法
- **段落内联图片处理**：遍历 `w:p` 的直接子元素（`w:r` 和 `w:hyperlink`），提取 `w:drawing` → `a:blip` → `r:embed`，解析为 Asset 并关联到段落的 `asset_ids`，文本用 `[图片: filename]` 占位
- **段落超链接处理**：处理 `w:hyperlink` 元素，提取显示文字和目标 URL，分类为视频/图片/附件/普通网页链接，附件/视频/图片链接创建 Asset，普通网页 URL 写入 `metadata.link_urls`
- **图片预提取重构**：`_extract_images` 改为 `_build_image_asset_map`，图片存入 `state._image_asset_map` 供后续关联，不再创建独立的 `ElementType.image` 元素
- **表格单元格资源处理**：按 `w:tc` 的直接子元素遍历，提取 `w:drawing` 和 `w:hyperlink`，单元格存储从 `str` 改为 `(text, asset_ids)` 元组，表格级 `asset_ids` 汇总所有单元格资源
- **视频提取更新**：使用 `utils.VIDEO_URL_RE` 和 `utils.guess_mime`，不再创建独立的 `ElementType.video` 元素，Asset 存入 `state.assets`
- **parse() 入口整合**：新流程包含 `_build_image_asset_map` → body 遍历 → `flush_elements` → `_extract_videos` → `_link_assets_to_elements` → `compute_hash`

## Capabilities

### Modified Capabilities
- `docx-parsing`：标题样式识别增强（非英文样式名支持）、内联图片/超链接处理、表格单元格资源处理、图片/视频提取重构、公共基础设施迁移

## Impact

- **修改文件**：`parsers/docx_parser.py`（约 250 行新增/修改，约 80 行删除）
- **测试**：[test_docx_parser.py](knowledge_base_system/tests/test_docx_parser.py)（新增 11+ 测试用例，适配已有图片测试）
- **Breaking 变更**：图片不再创建独立 `ElementType.image` 元素，而是关联到段落/表格的 `asset_ids`；视频不再创建独立 `ElementType.video` 元素。下游如有依赖独立 image/video 元素的逻辑需适配
- **API 兼容**：`ParseResult` 结构不变，`elements` 和 `assets` 的关联关系变更
