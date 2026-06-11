# Document Ingestion (Delta)

> 基于 `openspec/specs/document-ingestion/spec.md`，修改解析器选择机制以支持多格式。

## MODIFIED Requirements

### Requirement: 将文档解析为结构化元素

系统 SHALL 根据文档的 `source_type` 通过解析器注册表自动选择对应解析器，将文档解析为 ParsedElement 树，保留文档结构。当前支持的格式包括 Markdown/TXT 和 DOCX。

#### Scenario: 解析含标题、段落和列表的简单 Markdown

- **WHEN** 提交包含 `# 标题`、段落文字和项目符号列表的 Markdown 文档
- **THEN** 解析器按正确 `sequence_order` 生成类型为 `title`、`paragraph` 和 `list` 的 ParsedElement，`parent_element_id` 反映列表层级关系

#### Scenario: 解析 Markdown 表格

- **WHEN** Markdown 文档包含带表头和多行数据的表格
- **THEN** 解析器生成 `table` 元素，其 `structured_data.table` 包含 `caption`、`headers` 和 `rows`
- **AND** 每个单元格至少保留 `text` 和 `asset_ids`，以便语义层将表格转写为自然语言

#### Scenario: 解析图片链接

- **WHEN** Markdown 文档包含 `![alt](https://example.com/img.png)`
- **THEN** 解析器生成 `image` 元素，`asset_ids` 引用创建的 Asset，`text` 包含 alt 文本

#### Scenario: 解析视频链接

- **WHEN** Markdown 文档包含视频 URL 或 `[video](https://example.com/video.mp4)`
- **THEN** 解析器生成 `video` 元素，`asset_ids` 引用创建的 Asset

#### Scenario: 解析嵌入文档链接

- **WHEN** Markdown 文档包含指向其他文档的链接 `[子文档](https://example.com/child.md)`
- **THEN** 解析器生成 `embedded_document` 元素，`embedded_doc_id` 设为子文档的 `doc_id`

#### Scenario: 解析代码块

- **WHEN** Markdown 文档包含带语言标注的围栏代码块
- **THEN** 解析器生成 `code` 元素，`text` 为代码内容，`metadata.language` 为标注的语言

#### Scenario: 根据 source_type 自动选择解析器

- **WHEN** 提交 `source_type="docx"` 的文档
- **THEN** 管线通过 ParserRegistry 获取 DocxParser 并执行解析
- **AND** 提交 `source_type="markdown"` 的文档时通过 ParserRegistry 获取 MarkdownParser

#### Scenario: 不支持的文档类型

- **WHEN** 提交 `source_type` 不在任何已注册解析器支持列表中的文档
- **THEN** 系统返回不支持格式的错误，包含已支持的 source_type 列表
