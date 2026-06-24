## Why

当前 PPTX 解析器能从形状和文本运行中提取超链接 URL 并创建 Asset，但存在三个关键缺陷：

1. **链接文字丢失**：运行级超链接的显示文字虽然已包含在 `paragraph.text` 中，但没有显式记录"哪段文字对应哪个 URL"的映射关系，语义抽取器无法利用这些关联
2. **资源分类逻辑分散**：`_asset_type_for_url`、`_is_video_url`、`_is_audio_url`、`_guess_mime` 在 `PptxParser` 内部实现，而 `parsers/utils.py` 已有 `is_video_url`、`is_attachment_url`、`guess_mime`、`MIME_MAP` 等公共工具，存在重复
3. **图片超链接未记录**：图片形状如果同时带有超链接（如点击图片跳转到文档），链接信息未被写入 `ParsedElement`

此次改动让 PPTX 中的超链接成为"真实可追溯的资源关联"——链接文字保留在 `structured_data.links` 中，资源按类型正确分类并被下游 pipeline 处理，消除重复代码。

## What Changes

- 在 `parsers/utils.py` 添加 `classify_link` 公共函数，按 URL 后缀和域名特征分类为 `image`/`video`/`audio`/`document`/`url`
- 在 `PptxParser` 中新增 `_collect_shape_links` 方法，遍历形状级和运行级超链接，收集 `{text, url, link_type}` 三元组
- 修改 `_add_text_shape` 方法（普通段落和列表两个分支），调用 `_collect_shape_links` 并将链接信息写入 `structured_data.links`
- 修改 `_add_image` 方法，当图片形状带有超链接时，将链接信息写入 `structured_data.links`
- `_asset_type_for_url` 改为调用 `classify_link`，替代内部 `_is_video_url`/`_is_audio_url` 判断
- `_guess_mime` 改为调用 `parsers.utils.guess_mime`，消除 MIME 映射表重复
- 删除不再需要的 `_is_video_url`、`_is_audio_url` 方法、`VIDEO_URL_RE`、`AUDIO_URL_RE` 类属性、`_guess_mime` 静态方法
- 更新测试用例，验证超链接文字保留、链接分类、资源关联的正确性

## Capabilities

### New Capabilities
<!-- 本次改动不引入新的 capability，仅增强已有 pptx-parsing 的行为 -->

### Modified Capabilities
- `pptx-parsing`: 超链接文字保留到 `ParsedElement.structured_data.links`；资源分类改用公共 `classify_link` 函数；MIME 推断改用公共 `guess_mime` 函数；删除内部重复的分类/推断逻辑

## Impact

- **公共工具层**：[utils.py](knowledge_base_system/parsers/utils.py) — 新增 `classify_link` 函数
- **解析器层**：[pptx_parser.py](knowledge_base_system/parsers/pptx_parser.py) — 新增 `_collect_shape_links`；修改 `_add_text_shape`、`_add_image`、`_asset_type_for_url`；删除 `_is_video_url`、`_is_audio_url`、`_guess_mime`、`VIDEO_URL_RE`、`AUDIO_URL_RE`
- **测试层**：[test_pptx_parser.py](knowledge_base_system/tests/test_pptx_parser.py) — 新增超链接文字保留、链接分类、`classify_link` 单元测试用例
- **下游影响**：`ParsedElement.structured_data.links` 新增字段，语义抽取器（`SemanticExtractor`）可读取链接信息生成更丰富的知识块；不影响现有 API 契约
