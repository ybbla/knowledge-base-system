# HTML Parsing

## Purpose

定义 HTML/HTM 文档解析能力，将静态网页内容转换为统一的 `ParseResult`、`ParsedElement` 和 `Asset`，并与现有 Markdown、DOCX、XLSX 解析下游契约保持兼容。

## Requirements

### Requirement: 将 HTML 文档解析为统一结构

系统 SHALL 将 `.html` 和 `.htm` 文档解析为统一的 `ParseResult`，输出 `Document`、`ParsedElement` 和 `Asset`，并与 MarkdownParser、DocxParser、XlsxParser 的下游契约保持兼容。

#### Scenario: 解析 HTML 标题层级

- **GIVEN** 一个 HTML 文档包含 `h1`、`h2` 和 `h3` 标题
- **WHEN** 调用 `HtmlParser.parse(doc)`
- **THEN** 系统为每个标题生成一个 `title` 类型 ParsedElement
- **AND** `title.text` 为标题的纯文本内容
- **AND** `metadata.heading_level` 记录对应标题等级
- **AND** `source_location.section_path` 按标题层级维护当前路径

#### Scenario: 返回 ParseResult

- **GIVEN** 一个包含标题和正文的 HTML 文档
- **WHEN** 调用 `HtmlParser.parse(doc)`
- **THEN** 系统返回 `ParseResult`
- **AND** `result.doc.source_hash` 以 `sha256:` 开头
- **AND** 所有 ParsedElement 的 `doc_id` 与输入 Document 一致

#### Scenario: 跳过脚本和样式内容

- **GIVEN** 一个 HTML 文档包含 `script`、`style`、`noscript` 或 `template` 节点
- **WHEN** 解析该 HTML 文档
- **THEN** 系统 SHALL 不将这些节点中的内容生成 ParsedElement
- **AND** 解析过程不因这些节点失败

### Requirement: 将 HTML 正文结构解析为元素

系统 SHALL 将 HTML 正文中的段落、引用块、列表和代码块解析为统一 ParsedElement，保留文档顺序和来源上下文。

#### Scenario: 解析段落和引用块

- **GIVEN** HTML 文档在正文中包含 `p` 和 `blockquote`
- **WHEN** 解析该 HTML 文档
- **THEN** 系统生成 `paragraph` 类型 ParsedElement
- **AND** 段落文本为去除多余空白后的可读文本
- **AND** `source_location.section_path` 使用最近标题路径

#### Scenario: 解析有序和无序列表

- **GIVEN** HTML 文档包含 `ul` 和 `ol` 列表
- **WHEN** 解析该 HTML 文档
- **THEN** 系统生成 `list` 类型容器元素
- **AND** 每个列表项生成归属于该容器的 `paragraph` 子元素
- **AND** 列表容器 metadata 记录 `ordered=true` 或 `ordered=false`

#### Scenario: 解析代码块

- **GIVEN** HTML 文档包含 `pre` 或 `code` 代码块
- **WHEN** 解析该 HTML 文档
- **THEN** 系统生成 `code` 类型 ParsedElement
- **AND** `text` 保留代码文本
- **AND** 若能从 class 或 language 标记识别语言，则写入 `metadata.language`

### Requirement: 将 HTML 表格解析为表格元素

系统 SHALL 将 HTML `table` 节点解析为 `table` 类型 ParsedElement，并保留行列结构用于语义层转写自然语言。

#### Scenario: 解析简单 HTML 表格

- **GIVEN** HTML 文档包含一个带 `caption`、表头和多行数据的 `table`
- **WHEN** 解析该 HTML 文档
- **THEN** 系统生成一个 `table` 类型 ParsedElement
- **AND** `structured_data.table.caption` 来自 `caption`
- **AND** `structured_data.table.headers` 来自 `thead` 或首行表头
- **AND** `structured_data.table.rows` 包含后续数据行
- **AND** 每个单元格至少包含 `text` 和 `asset_ids`

#### Scenario: 保留单元格跨度元数据

- **GIVEN** HTML 表格单元格包含 `rowspan` 或 `colspan`
- **WHEN** 解析该表格
- **THEN** 系统 SHALL 在单元格 metadata 中记录跨度信息
- **AND** 系统不得丢弃该单元格文本

#### Scenario: 处理嵌套表格

- **GIVEN** HTML 表格单元格中包含嵌套 `table`
- **WHEN** 解析该 HTML 文档
- **THEN** 系统 SHALL 避免将嵌套表格文本重复污染父表格单元格
- **AND** 可将嵌套表格解析为独立 `table` 元素

### Requirement: 识别 HTML 中的图片、视频和附件资源

系统 SHALL 识别 HTML 中可追溯的图片、视频和附件资源，创建或关联 Asset，并在 ParsedElement 中保留 `asset_ids`。

#### Scenario: 识别图片资源

- **GIVEN** HTML 文档包含 `img src="https://example.com/a.png"` 且存在 `alt` 文本
- **WHEN** 解析该 HTML 文档
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** Asset 的 `original_uri` 为图片 URL
- **AND** Asset 的 `status` 为 `pending`
- **AND** 对应 ParsedElement 的 `asset_ids` 引用该 Asset
- **AND** Asset metadata 记录 `alt` 文本

#### Scenario: 识别视频资源

- **GIVEN** HTML 文档包含 `video`、`source`、视频文件 URL、YouTube/Vimeo URL 或视频 iframe
- **WHEN** 解析该 HTML 文档
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** Asset 的 `original_uri` 为视频 URL
- **AND** Asset 的 `status` 为 `pending`
- **AND** 阶段 4 不要求下载或理解视频内容

#### Scenario: 识别附件资源候选

- **GIVEN** HTML 文档包含指向 PDF、DOCX、XLSX、PPTX 或其他下载文件的 `a`、`iframe`、`embed` 或 `object`
- **WHEN** 解析该 HTML 文档
- **THEN** 系统 SHALL 保留该 URL 的来源信息
- **AND** 若创建 Asset，则 Asset 的 `asset_type` 为 `attachment`
- **AND** 阶段 4 不要求下载或递归解析该附件

### Requirement: HTML 解析器实现统一解析器接口

系统 SHALL 实现 `DocumentParser` 抽象接口，声明 `SUPPORTED_TYPES = {"html", "htm"}`，并支持从 `metadata.raw_content` 或 `file://` / `minio://` 入库链路提供的内容中解析 HTML 文档。

#### Scenario: 支持类型检查

- **WHEN** 调用 `HtmlParser.supports("html")` 和 `HtmlParser.supports("htm")`
- **THEN** 两者均返回 `True`

#### Scenario: 大小写不敏感

- **WHEN** 调用 `HtmlParser.supports("HTML")` 或 `HtmlParser.supports("HTM")`
- **THEN** 返回 `True`

#### Scenario: 不支持其他网页格式

- **WHEN** 调用 `HtmlParser.supports("xhtml")`
- **THEN** 返回 `False`

#### Scenario: 空 HTML 文档降级为失败

- **GIVEN** 文档声明 `source_type="html"` 但内容为空
- **WHEN** 入库管线调用解析器
- **THEN** 入库 job 状态变为 `failed`
- **AND** 错误信息包含 HTML 解析失败原因
