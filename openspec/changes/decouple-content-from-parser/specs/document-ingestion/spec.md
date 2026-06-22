# Document Ingestion (Delta)

## MODIFIED Requirements

### Requirement: 将文档解析为结构化元素

系统 SHALL 根据文档的 `source_type` 通过解析器注册表自动选择对应解析器，将文档解析为 ParsedElement 树，保留文档结构。Pipeline SHALL 将文档内容（`bytes` 或 `str`）作为显式参数传给 `parser.parse(doc, content)`。

#### Scenario: 解析含标题、段落和列表的简单 Markdown

- **WHEN** 提交包含 `# 标题`、段落文字和项目符号列表的 Markdown 文档
- **THEN** 解析器按正确 `sequence_order` 生成类型为 `title`、`paragraph` 和 `list` 的 ParsedElement，`parent_element_id` 反映列表层级关系

#### Scenario: 根据 source_type 自动选择解析器

- **WHEN** 提交 `source_type="docx"` 的文档
- **THEN** 管线通过 ParserRegistry 获取 DocxParser 并执行解析
- **AND** 提交 `source_type="markdown"` 的文档时通过 ParserRegistry 获取 MarkdownParser
- **AND** 提交 `source_type="xlsx"` 的文档时通过 ParserRegistry 获取 XlsxParser
- **AND** 提交 `source_type="html"` 或 `"htm"` 的文档时通过 ParserRegistry 获取 HtmlParser
- **AND** 提交 `source_type="pptx"` 的文档时通过 ParserRegistry 获取 PptxParser

#### Scenario: 不支持的文档类型

- **WHEN** 提交 `source_type` 不在任何已注册解析器支持列表中的文档
- **THEN** 系统返回不支持格式的错误，包含已支持的 source_type 列表

## ADDED Requirements

### Requirement: 上传路径直接传递内容给 Pipeline

系统 SHALL 在上传接口中将文件内容读入内存后直接传给 `ingestion_pipeline.ingest(doc, raw_content=file_content)`，消除 MinIO 写后即读回环。

#### Scenario: 上传后内容直接传 ingest

- **GIVEN** 用户上传一个 DOCX 文件
- **WHEN** `upload_document()` 处理该文件
- **THEN** 文件内容读入内存后直接传给 `ingest(doc, raw_content=bytes_content)`
- **AND** Pipeline 将 `raw_content` 原样传给 `parser.parse(doc, raw_content)`
- **AND** Pipeline 不从 MinIO 读回该文件内容

### Requirement: 降级路径从 MinIO 或 file:// 读取内容

系统 SHALL 在 `ingest()` 未收到 `raw_content` 时，从 `doc.source_uri` 降级读取内容，并根据 `parser.CONTENT_IS_TEXT` 决定返回 `str` 还是 `bytes`。

#### Scenario: 降级路径——从 MinIO 读取

- **GIVEN** `ingest()` 被调用时未传入 `raw_content`，且 `doc.source_uri` 以 `minio://` 开头
- **WHEN** Pipeline 执行 `_run_create()`
- **THEN** Pipeline SHALL 从 MinIO 读取原始字节
- **AND** 根据 `parser.CONTENT_IS_TEXT` 决定是否 decode 为 str
- **AND** 解析器正常完成解析

#### Scenario: 降级路径——从 file:// 读取

- **GIVEN** `ingest()` 被调用时未传入 `raw_content`，且 `doc.source_uri` 以 `file://` 开头
- **WHEN** Pipeline 执行 `_run_create()`
- **THEN** Pipeline SHALL 从本地文件系统读取原始字节
- **AND** 根据 `parser.CONTENT_IS_TEXT` 决定是否 decode 为 str

### Requirement: 解析器接口显式接收内容

系统 SHALL 定义 `DocumentParser.parse(doc, content)` 接口，其中 `content: bytes | str` 为必传参数。解析完成后 `doc.metadata` 不含原始内容。

#### Scenario: 二进制格式解析器接收 bytes

- **GIVEN** DocxParser 被 Pipeline 调用
- **WHEN** Pipeline 传入 `content=b"PK\x03\x04..."` （bytes）
- **THEN** DocxParser 直接使用 `content` 参数解析
- **AND** 不访问 `doc.metadata["raw_content"]`

#### Scenario: 文本格式解析器接收 str

- **GIVEN** MarkdownParser 被 Pipeline 调用
- **WHEN** Pipeline 传入 `content="# 标题\n\n正文内容"` （str）
- **THEN** MarkdownParser 直接使用 `content` 参数解析
- **AND** 不访问 `doc.metadata["raw_content"]`

#### Scenario: 解析完成后 doc.metadata 不含 raw_content

- **GIVEN** 任意格式文档完成解析
- **WHEN** `parser.parse(doc, content)` 返回
- **THEN** `doc.metadata` 中不包含 `"raw_content"` 键
