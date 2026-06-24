# DOCX Parsing (Delta)

## MODIFIED Requirements

### Requirement: 将 DOCX 文档解析为结构化元素

系统 SHALL 将 DOCX 文档解析为 ParsedElement 树，保留文档结构，并将内联图片、超链接等资源关联到所属元素。

#### Scenario: 解析非英文样式标题

- **GIVEN** DOCX 文档使用中文 Word 创建，标题样式名为 "标题 1"
- **WHEN** 解析该文档
- **THEN** 解析器正确生成 `title` 类型 ParsedElement，`metadata.heading_level=1`
- **AND** 对法文 "Titre 1"、德文 "Überschrift 1"、西班牙文 "Título 1"、意大利文 "Intestazione 1"、日文 "見出し 1" 同样正确识别

#### Scenario: 解析英文样式标题（回归）

- **GIVEN** DOCX 文档使用英文 Word 创建，标题样式名为 "Heading 1"
- **WHEN** 解析该文档
- **THEN** 行为与修改前一致，正确生成 `title` 类型 ParsedElement

#### Scenario: 非标题样式不受影响

- **GIVEN** DOCX 文档包含 "Normal"、"List Paragraph"、"List Bullet" 等非标题样式
- **WHEN** 解析该文档
- **THEN** 这些样式不会被误识别为标题
- **AND** List 样式 + 编号段落（`w:numPr`）被强制识别为列表而非标题

#### Scenario: 解析段落中内联图片

- **GIVEN** DOCX 文档包含段落，段落中嵌有内联图片（`w:drawing` → `a:blip`）
- **WHEN** 解析该文档
- **THEN** 该图片创建为 Asset，asset_id 关联到段落的 `asset_ids`
- **AND** 段落文本中包含 `[图片: <filename>]` 占位符
- **AND** Asset 不再创建独立的 `ElementType.image` 类型 ParsedElement

#### Scenario: 纯图片段落（无文本）仍创建元素

- **GIVEN** DOCX 文档包含一个只有内联图片、没有文本的段落
- **WHEN** 解析该文档
- **THEN** 该段落仍然创建 ParsedElement（`ElementType.paragraph`）
- **AND** 图片关联到该段落元素的 `asset_ids`

#### Scenario: 解析段落中普通网页超链接

- **GIVEN** DOCX 文档包含段落，段落中有超链接（`w:hyperlink`）指向普通网页 URL（如 `https://example.com`）
- **WHEN** 解析该文档
- **THEN** URL 写入该段落 ParsedElement 的 `metadata.link_urls`
- **AND** 段落文本保留超链接的显示文字，不追加 URL

#### Scenario: 解析段落中附件链接

- **GIVEN** DOCX 文档包含段落，段落中有超链接指向附件文件（如 `.pdf`、`.docx`）
- **WHEN** 解析该文档
- **THEN** 为附件创建 `AssetType.attachment` 类型 Asset
- **AND** Asset 的 asset_id 关联到段落的 `asset_ids`
- **AND** 段落文本只保留超链接的显示文字

#### Scenario: 解析段落中视频链接

- **GIVEN** DOCX 文档包含段落，段落中有超链接指向视频 URL（如 `https://youtube.com/...`）
- **WHEN** 解析该文档
- **THEN** 为视频创建 `AssetType.video` 类型 Asset
- **AND** Asset 的 asset_id 关联到段落的 `asset_ids`
- **AND** 段落文本只保留超链接的显示文字

#### Scenario: 解析段落中图片链接

- **GIVEN** DOCX 文档包含段落，段落中有超链接指向图片 URL（如 `https://example.com/photo.png`）
- **WHEN** 解析该文档
- **THEN** 为图片创建 `AssetType.image` 类型 Asset
- **AND** Asset 的 asset_id 关联到段落的 `asset_ids`
- **AND** 段落文本只保留超链接的显示文字

#### Scenario: 段落中文本和超链接交错出现保持顺序

- **GIVEN** DOCX 段落结构为：普通文本 → 超链接 → 普通文本
- **WHEN** 解析该文档
- **THEN** 段落文本按原文顺序拼接：普通文本 + 超链接显示文字 + 普通文本

### Requirement: 将 DOCX 表格解析为结构化数据

系统 SHALL 将 DOCX 表格（`w:tbl`）解析为包含行列结构、表头和单元格资源的 `structured_data`。

#### Scenario: 解析表格单元格内嵌图片

- **GIVEN** DOCX 文档包含表格，表格某个单元格中嵌有内联图片（结构为 `w:tc` → `w:p` → `w:r` → `w:drawing` → `a:blip` → `r:embed`）
- **WHEN** 解析该文档
- **THEN** 解析器遍历 `w:tc` 中的每个 `w:p` 子元素，在 `w:p` 内发现 `w:drawing` → 通过 `r:embed` rId 在 `docx.part.rels` 中查找 → 匹配 `state._image_asset_map` 中的 Asset
- **AND** 该单元格的 `asset_ids` 包含对应 Asset 的 ID
- **AND** 表格级 `asset_ids` 汇总所有单元格的资源 ID（去重）

#### Scenario: 解析表格单元格内超链接

- **GIVEN** DOCX 文档包含表格，表格某个单元格中有超链接（结构为 `w:tc` → `w:p` → `w:hyperlink`）
- **WHEN** 解析该文档
- **THEN** 解析器遍历 `w:tc` 中的每个 `w:p` 子元素，在 `w:p` 内发现 `w:hyperlink` → 提取显示文字 + 通过 `r:id` 获取目标 URL
- **AND** 为图片链接（如 `https://example.com/photo.png`）创建 `AssetType.image` 类型 Asset，关联到该单元格的 `asset_ids`
- **AND** 为视频链接（如 `https://youtube.com/watch?v=xxx`）创建 `AssetType.video` 类型 Asset，关联到该单元格的 `asset_ids`
- **AND** 为文档/附件链接（如 `.pdf`、`.docx`）创建 `AssetType.attachment` 类型 Asset，关联到该单元格的 `asset_ids`
- **AND** 普通网页链接的 URL 记录到单元格 metadata，不创建 Asset
- **AND** 所有类型链接的显示文字保留到单元格文本中（不追加 URL）

#### Scenario: 表格单元格多个段落保持内容

- **GIVEN** DOCX 表格某个单元格包含多个 `w:p`（多个段落）
- **WHEN** 解析该文档
- **THEN** 每个 `w:p` 的文本和资源分别提取
- **AND** 多个段落文本用换行符分隔拼接
- **AND** 所有段落的 asset_ids 合并到该单元格

#### Scenario: 合并单元格正确传递 asset_ids

- **GIVEN** DOCX 文档包含有 `gridSpan` 水平合并或 `vMerge` 垂直合并的表格，合并单元格中有图片
- **WHEN** 解析该文档
- **THEN** `vertical_merges` 字典存储 `(text, asset_ids)` 元组而非纯文本
- **AND** `vMerge="continue"` 的单元格从 `vertical_merges` 继承文本和 asset_ids
- **AND** `gridSpan` 水平扩展的单元格均获得图片的 asset_id 关联

### Requirement: 图片预提取为 asset map

系统 SHALL 将 DOCX 内嵌图片预提取为 asset map（key 为 zip 内路径），供后续段落/表格通过 rId 查找关联，不再创建独立的 `ElementType.image` 元素。

#### Scenario: 图片通过 rId 关联到所在元素

- **GIVEN** DOCX 文档 `word/media/` 中包含图片，且段落中的 `w:drawing` 通过 rId 引用该图片
- **WHEN** 解析该文档
- **THEN** 通过 `docx.part.rels[rId].target_ref` 匹配到 `state._image_asset_map` 中的 Asset
- **AND** Asset 存入 `state.assets`，通过 `_link_assets_to_elements` 回填 `source_element_id`

#### Scenario: 嵌入图片不再创建独立 image 元素

- **GIVEN** DOCX 文档包含嵌入图片
- **WHEN** 解析该文档
- **THEN** `result.elements` 中不再包含 `ElementType.image` 类型的元素
- **AND** 图片作为 Asset 关联到包含它的段落或表格元素

### Requirement: 视频链接提取

系统 SHALL 从段落/表格文本中识别视频链接并创建 `AssetType.video` 类型 Asset，不再创建独立的 `ElementType.video` 元素。

#### Scenario: 段落文本中的视频链接

- **GIVEN** DOCX 文档段落文本中包含视频 URL（如 `https://youtube.com/watch?v=xxx`）
- **WHEN** 解析该文档
- **THEN** 为该 URL 创建 `AssetType.video` 类型 Asset
- **AND** Asset 存入 `state.assets`，通过 `_link_assets_to_elements` 关联到所在元素
- **AND** 不创建独立的 `ElementType.video` 类型 ParsedElement

#### Scenario: 视频链接去重

- **GIVEN** DOCX 文档多个段落包含相同视频 URL
- **WHEN** 解析该文档
- **THEN** 同一视频 URL 只创建一个 Asset

## ADDED Requirements

### Requirement: 使用公共基础设施

系统 SHALL 使用 `parsers/utils.py` 和 `_BaseParseState` 基类，不再内联重复代码。

#### Scenario: 解析状态继承基类

- **GIVEN** DocxParser 创建内部解析状态
- **WHEN** 初始化 `_DocxParseState`
- **THEN** `_DocxParseState` 为 `@dataclass` 继承 `_BaseParseState`
- **AND** 共享 `doc_id`、`doc_version`、`elements`、`_seq`、`_section_path`、`_next_seq()` 从基类继承
- **AND** 子类扩展 `_tracked_assets`、`_link_urls`、`_image_asset_map`、`assets` 等特有字段

#### Scenario: 公共工具导入

- **WHEN** DocxParser 需要 MIME 推断、URL 识别、文本规范化
- **THEN** 从 `parsers/utils.py` 导入 `guess_mime`、`is_video_url`、`is_attachment_url`、`normalize_text`、`VIDEO_URL_RE`、`HTTP_URL_RE`、`MIME_MAP`、`ATTACHMENT_EXTENSIONS`
- **AND** 不再定义本地 `VIDEO_URL_RE`
- **AND** 不再使用本地 MIME 字典

### Requirement: 段落资源跟踪

系统 SHALL 通过 `_DocxParseState` 的资源跟踪机制，在解析段落时自动消费并关联跟踪的 asset_ids 和 link_urls。

#### Scenario: add_paragraph 消费跟踪的资源

- **GIVEN** 解析过程中通过 `track_asset()` 记录了资源 ID，通过 `track_link_url()` 记录了链接 URL
- **WHEN** 调用 `state.add_paragraph(text)`
- **THEN** 创建的 ParsedElement 的 `asset_ids` 包含所有已跟踪的资源 ID
- **AND** 创建的 ParsedElement 的 `metadata.link_urls` 包含所有已跟踪的链接 URL
- **AND** 跟踪列表被清空

#### Scenario: 资源跟踪在标题/列表项中自动清空

- **GIVEN** 解析过程中已跟踪了某些资源 ID
- **WHEN** 遇到新的标题或列表项
- **THEN** 之前跟踪的资源被丢弃（不关联到新标题/列表项），跟踪列表清空

### Requirement: Asset 到元素的回填关联

系统 SHALL 在 `flush_elements()` 后，通过 `_link_assets_to_elements` 将 Asset 的 `source_element_id` 回填为包含该 Asset 的元素的 `element_id`。

#### Scenario: Asset source_element_id 正确回填

- **GIVEN** 解析完成后，elements 的 element_id 已生成，每个 element 的 asset_ids 已填充
- **WHEN** 调用 `_link_assets_to_elements(elements, assets)`
- **THEN** 每个 Asset 的 `source_element_id` 被设置为包含其 asset_id 的元素的 `element_id`
- **AND** 未被任何元素引用的 Asset 的 `source_element_id` 保持为空字符串
