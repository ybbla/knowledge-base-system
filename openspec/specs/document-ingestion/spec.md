# Document Ingestion

## Purpose

将 Markdown/TXT/DOCX/XLSX 文档解析为结构化元素树（ParsedElement），创建 Document 和 Asset 记录，并递归处理嵌入文档。Document 包含业务分类 `category`，入库请求通过 `source_uri` 引用文件内容。

> 同步自 change `implement-mvp-phase-1`，日期 2026-06-09；更新自 change `align-data-model-and-api-with-updated-design`，日期 2026-06-10；更新自 change `phase-4-xlsx-parsing` 和 `fix-root-parse-and-minio-test-isolation`，日期 2026-06-13。

## Requirements

### Requirement: 将文档解析为结构化元素

系统 SHALL 根据文档的 `source_type` 通过解析器注册表自动选择对应解析器，将文档解析为 ParsedElement 树，保留文档结构。当前支持的格式包括 Markdown/TXT、DOCX、XLSX、HTML/HTM 和 PPTX。

#### Scenario: 解析含标题、段落和列表的简单 Markdown

- **WHEN** 提交包含 `# 标题`、段落文字和项目符号列表的 Markdown 文档
- **THEN** 解析器按正确 `sequence_order` 生成类型为 `title`、`paragraph` 和 `list` 的 ParsedElement，`parent_element_id` 反映列表层级关系

#### Scenario: 解析 Markdown 表格

- **WHEN** Markdown 文档包含带表头和多行数据的表格
- **THEN** 解析器生成 `table` 元素，其 `structured_data.table` 包含 `caption`、`headers` 和 `rows`
- **AND** 每个单元格至少保留 `text` 和 `asset_ids`，以便语义层将表格转写为自然语言

#### Scenario: 解析 XLSX 工作簿

- **WHEN** 提交 `source_type="xlsx"` 的文档
- **THEN** 管线通过 ParserRegistry 获取 XlsxParser 并执行解析
- **AND** 解析器生成工作表级 `title` 元素和表格区域对应的 `table` 元素
- **AND** `structured_data.table` 与 Markdown/DOCX 表格结构兼容

#### Scenario: 解析 HTML 文档

- **GIVEN** 提交 `source_type="html"` 或 `source_type="htm"` 的文档
- **WHEN** 入库管线处理该文档
- **THEN** 管线通过 ParserRegistry 获取 HtmlParser 并执行解析
- **AND** 解析器生成标题、段落、列表、表格和资源元素
- **AND** `structured_data.table` 与 Markdown/DOCX/XLSX 表格结构兼容

#### Scenario: 解析 PPTX 演示文稿

- **GIVEN** 提交 `source_type="pptx"` 的文档
- **WHEN** 入库管线处理该文档
- **THEN** 管线通过 ParserRegistry 获取 PptxParser 并执行解析
- **AND** 解析器生成幻灯片标题、段落、列表、表格和资源元素
- **AND** `structured_data.table` 与 Markdown/DOCX/XLSX/HTML 表格结构兼容

#### Scenario: 解析图片链接

- **WHEN** Markdown、HTML 或 PPTX 文档包含图片链接或内嵌图片
- **THEN** 解析器生成或关联 `image` 资源，`asset_ids` 引用创建的 Asset，`text` 包含可用的 alt 文本、图片标记或来源说明

#### Scenario: 解析视频链接

- **WHEN** Markdown、XLSX、HTML 或 PPTX 文档包含视频 URL 或 `[video](https://example.com/video.mp4)`
- **THEN** 解析器生成或关联 `video` 资源，`asset_ids` 引用创建的 Asset

#### Scenario: 解析嵌入文档链接

- **WHEN** Markdown 文档包含指向其他文档的链接 `[子文档](https://example.com/child.md)`
- **THEN** 解析器生成 `embedded_document` 元素，`embedded_doc_id` 设为子文档的 `doc_id`

#### Scenario: 解析代码块

- **WHEN** Markdown 或 HTML 文档包含代码块
- **THEN** 解析器生成 `code` 元素，`text` 为代码内容，`metadata.language` 在可识别时记录标注语言

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

### Requirement: 解析过程中创建 Document 和 Asset 记录

系统 SHALL 在解析时为文档创建 Document 记录（含 `category`），为每个识别到的资源创建 Asset 记录。

#### Scenario: 创建 Document 记录

- **WHEN** 文档提交解析
- **THEN** 创建 Document 记录，包含 `doc_id`、`title`、`source_type`、`source_uri`、`source_hash`、`version=1`、`status="pending"`、`category`、`ingest_job_id` 和时间戳
- **AND** 若 `category` 未指定，默认值为 `"通用"`
- **AND** 若文档来自嵌入文档，记录 `parent_doc_id`、`root_doc_id` 和 `metadata.embed_path`

#### Scenario: 为图片创建 Asset 记录

- **WHEN** 解析到图片链接
- **THEN** 创建 Asset 记录，包含 `asset_id`、`doc_id`、`source_element_id`、`asset_type="image"`、`original_uri`、`storage_uri=null`、`content_hash`、`status="pending"`、`extracted_text=null`、`error_message=null` 和 `created_at`/`updated_at`

#### Scenario: 为视频链接创建 Asset 记录

- **WHEN** 解析到视频 URL 或视频链接
- **THEN** 创建 Asset 记录，包含 `asset_type="video"`、`original_uri`、`storage_uri=null`、`status="pending"` 和来源元素信息
- **AND** 阶段 1 不强制下载或理解视频内容

### Requirement: 入库请求仅接受 source_uri

系统 SHALL 在 `/ingest` 接口中要求 `source_uri` 为必填，不再接受内联 `content`。

#### Scenario: 通过 source_uri 提交入库

- **WHEN** 客户端调 `POST /ingest` 提交 `source_uri`（来自 `/upload`）、`source_type`、`title`、`category`
- **THEN** 系统接受请求，返回 202 和 `job_id`、`doc_ids`

#### Scenario: 未提供 source_uri 返回错误

- **WHEN** 客户端调 `POST /ingest` 未提供 `source_uri`
- **THEN** 系统返回 422 校验错误

#### Scenario: category 默认值

- **WHEN** 客户端调 `POST /ingest` 未指定 `category`
- **THEN** Document 的 `category` 为 `"通用"`

### Requirement: 处理递归嵌入文档并设置边界

系统 SHALL 递归解析嵌入文档至可配置的最大深度，并支持去重。系统 MUST 在一次入库任务中只解析并提交一次根文档元素；递归加载只能补充嵌入文档产生的 Document 和 ParsedElement，不得重复返回根文档 ParsedElement。

#### Scenario: 根文档只解析一次

- **GIVEN** 文档 A 不包含嵌入文档
- **WHEN** 提交文档 A 入库
- **THEN** 语义抽取层只接收文档 A 首次解析产生的 ParsedElement
- **AND** 文档 A 的标题、段落、表格或资源元素不得因递归加载重复出现

#### Scenario: 根文档包含嵌入文档时不重复根元素

- **GIVEN** 文档 A 包含嵌入文档 B
- **WHEN** 提交文档 A 入库
- **THEN** 语义抽取层接收文档 A 的 ParsedElement 一次
- **AND** 系统继续递归解析文档 B 并追加文档 B 的 ParsedElement
- **AND** 文档 A 的 ParsedElement 不因发现文档 B 被再次解析或再次追加

#### Scenario: 深度限制内递归解析

- **GIVEN** 文档 A 嵌入文档 B，文档 B 嵌入文档 C，max_depth=3
- **WHEN** 提交文档 A 入库
- **THEN** 三个文档全部被解析，每个 Document 的 `parent_doc_id` 和 `root_doc_id` 正确指向文档 A

#### Scenario: 超出最大深度

- **GIVEN** 文档 A 在深度 3 处嵌入文档 B，max_depth=3
- **WHEN** 提交文档 A 入库
- **THEN** 文档 B 不被递归解析，其 Document 记录标记 `metadata.skipped_reason="max_depth_exceeded"`

#### Scenario: 重复文档跳过

- **GIVEN** 同一文档（相同 `source_hash`）在递归链路中遇到两次
- **WHEN** 提交根文档入库
- **THEN** 重复文档被跳过，标记 `metadata.skipped_reason="duplicated_document"`

#### Scenario: 外部资源阶段 1 仅识别关联

- **GIVEN** 文档包含图片、视频或附件链接
- **WHEN** 提交文档入库
- **THEN** 系统创建 Asset 并与 ParsedElement 关联
- **AND** 阶段 1 不要求下载到 MinIO、不要求生成 `storage_uri`，后续资源处理可异步补齐
