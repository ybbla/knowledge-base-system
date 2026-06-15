## ADDED Requirements

### Requirement: 将 PPTX 演示文稿解析为统一结构

系统 SHALL 将 `.pptx` 演示文稿解析为统一的 `ParseResult`，输出 `Document`、`ParsedElement` 和 `Asset`，并与 MarkdownParser、DocxParser、XlsxParser 和 HtmlParser 的下游契约保持兼容。

#### Scenario: 解析多页演示文稿

- **GIVEN** 一个 PPTX 演示文稿包含多张幻灯片
- **WHEN** 调用 `PptxParser.parse(doc)`
- **THEN** 系统按幻灯片顺序生成 ParsedElement
- **AND** 每个元素 metadata 至少记录 `slide_index` 和 `slide_number`
- **AND** `result.doc.source_hash` 以 `sha256:` 开头
- **AND** 所有 ParsedElement 的 `doc_id` 与输入 Document 一致

#### Scenario: 为无标题幻灯片生成兜底上下文

- **GIVEN** 一张幻灯片没有标题占位符或可识别标题文本
- **WHEN** 解析该幻灯片
- **THEN** 系统 SHALL 使用 `幻灯片 {n}` 作为该页的兜底标题上下文
- **AND** 后续元素的 `source_location.section_path` 包含该兜底标题

#### Scenario: 空演示文稿降级为失败

- **GIVEN** 一个 PPTX 文件不包含任何可解析幻灯片或可读内容
- **WHEN** 入库管线调用 PptxParser
- **THEN** 入库 job 状态变为 `failed`
- **AND** 错误信息包含 PPTX 解析失败原因

### Requirement: 解析 PPTX 文本、标题和列表

系统 SHALL 将 PPTX 中的标题、文本框、正文占位符和项目符号列表解析为统一 ParsedElement，保留可追溯来源和稳定顺序。

#### Scenario: 解析标题占位符

- **GIVEN** 一张幻灯片包含标题占位符
- **WHEN** 解析该幻灯片
- **THEN** 系统生成 `title` 类型 ParsedElement
- **AND** `title.text` 为标题文本
- **AND** `source_location.section_path` 包含该标题文本
- **AND** metadata 记录 `heading_level=1`、`slide_index` 和形状来源信息

#### Scenario: 解析普通文本框

- **GIVEN** 一张幻灯片包含普通文本框
- **WHEN** 解析该文本框
- **THEN** 系统生成 `paragraph` 类型 ParsedElement
- **AND** `text` 为去除多余空白后的可读文本
- **AND** metadata 记录 `shape_id`、`shape_name`、`left`、`top`、`width` 和 `height`

#### Scenario: 解析项目符号列表

- **GIVEN** 一张幻灯片包含多条项目符号正文
- **WHEN** 解析该文本形状
- **THEN** 系统生成 `list` 类型容器元素
- **AND** 每条项目符号生成归属于该容器的 `paragraph` 子元素
- **AND** 子元素 metadata 记录项目符号层级或缩进信息

#### Scenario: 稳定生成阅读顺序

- **GIVEN** 同一幻灯片上存在多个文本形状
- **WHEN** 解析该幻灯片
- **THEN** 系统 SHALL 按 `top`、`left` 和原始形状索引生成稳定 `sequence_order`
- **AND** 不因 OOXML 内部顺序变化导致同一视觉布局下的解析顺序随机变化

### Requirement: 将 PPTX 表格解析为表格元素

系统 SHALL 将 PPTX 表格形状解析为 `table` 类型 ParsedElement，并保留行列结构用于语义层转写自然语言。

#### Scenario: 解析简单 PPTX 表格

- **GIVEN** 一张幻灯片包含一个首行为表头的表格形状
- **WHEN** 解析该表格
- **THEN** 系统生成一个 `table` 类型 ParsedElement
- **AND** `structured_data.table.headers` 来自首行
- **AND** `structured_data.table.rows` 包含后续数据行
- **AND** 每个单元格至少包含 `text`、`asset_ids` 和行列 metadata

#### Scenario: 保留表格来源信息

- **GIVEN** 一个 PPTX 表格形状位于第 2 张幻灯片
- **WHEN** 解析该表格
- **THEN** table metadata 记录 `slide_index`、`slide_number`、`shape_id`、行数、列数和形状坐标
- **AND** `source_location.section_path` 使用当前幻灯片标题上下文

### Requirement: 识别 PPTX 图片、视频和附件资源

系统 SHALL 识别 PPTX 中可追溯的图片、视频 URL、音频/视频媒体、附件和外部链接资源，创建或关联 Asset，并在 ParsedElement 中保留 `asset_ids`。

#### Scenario: 提取内嵌图片资源

- **GIVEN** PPTX 幻灯片包含内嵌图片
- **WHEN** 解析该图片形状
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** Asset 的 `status` 为 `pending`
- **AND** Asset 保留 MIME 类型、内容 hash 和原始字节
- **AND** 系统生成 `image` 类型 ParsedElement 并通过 `asset_ids` 引用该 Asset

#### Scenario: 识别文本中的视频 URL

- **GIVEN** PPTX 文本框包含 `https://example.com/demo.mp4`
- **WHEN** 解析该文本框
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** Asset 的 `original_uri` 为该视频 URL
- **AND** Asset 的 `status` 为 `pending`
- **AND** 阶段 4 不下载或理解视频内容

#### Scenario: 识别附件或外部文件链接

- **GIVEN** PPTX 形状超链接指向 `https://example.com/manual.pdf`
- **WHEN** 解析该形状
- **THEN** 系统 SHALL 保留该链接的来源信息
- **AND** 若创建 Asset，则 Asset 的 `asset_type` 为 `attachment`
- **AND** 阶段 4 不下载或递归解析该附件

#### Scenario: 去重同一文档内重复资源

- **GIVEN** 同一 PPTX 文档多处引用相同外部 URL 或相同媒体内容
- **WHEN** 解析该文档
- **THEN** 系统 SHALL 避免重复创建等价 Asset
- **AND** 多个 ParsedElement 可以通过 `asset_ids` 引用同一 Asset

### Requirement: PPTX 解析器实现统一解析器接口

系统 SHALL 实现 `DocumentParser` 抽象接口，声明 `SUPPORTED_TYPES = {"pptx"}`，并支持从 `metadata.raw_content` 或 `file://` / `minio://` 入库链路提供的字节内容中解析演示文稿。

#### Scenario: 支持类型检查

- **WHEN** 调用 `PptxParser.supports("pptx")`
- **THEN** 返回 `True`

#### Scenario: 大小写不敏感

- **WHEN** 调用 `PptxParser.supports("PPTX")`
- **THEN** 返回 `True`

#### Scenario: 不支持旧版 PPT

- **WHEN** 调用 `PptxParser.supports("ppt")`
- **THEN** 返回 `False`

#### Scenario: 无效 PPTX 文件降级为失败

- **GIVEN** 文档声明 `source_type="pptx"` 但内容不是有效 PPTX 文件
- **WHEN** 入库管线调用解析器
- **THEN** 入库 job 状态变为 `failed`
- **AND** 错误信息包含 PPTX 解析失败原因
