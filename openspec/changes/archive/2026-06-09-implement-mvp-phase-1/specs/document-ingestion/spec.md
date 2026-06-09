## ADDED Requirements

### Requirement: 将 Markdown 文档解析为结构化元素
系统 SHALL 将 Markdown 和 TXT 文档解析为 ParsedElement 树，保留文档结构。

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

#### Scenario: 不支持的文档类型
- **WHEN** 提交 `source_type` 不在支持列表中的文档
- **THEN** 系统返回不支持格式的错误

### Requirement: 解析过程中创建 Document 和 Asset 记录
系统 SHALL 在解析时为文档创建 Document 记录，为每个识别到的资源创建 Asset 记录。

#### Scenario: 创建 Document 记录
- **WHEN** 文档提交解析
- **THEN** 创建 Document 记录，包含 `doc_id`、`title`、`source_type`、`source_uri`、`source_hash`、`version=1`、`status="pending"`、`ingest_job_id` 和时间戳
- **AND** 若文档来自嵌入文档，记录 `parent_doc_id`、`root_doc_id` 和 `metadata.embed_path`

#### Scenario: 为图片创建 Asset 记录
- **WHEN** 解析到图片链接
- **THEN** 创建 Asset 记录，包含 `asset_id`、`doc_id`、`source_element_id`、`asset_type="image"`、`original_uri`、`storage_uri=null`、`content_hash`、`status="pending"`、`extracted_text=null`、`error_message=null` 和 `created_at`/`updated_at`

#### Scenario: 为视频链接创建 Asset 记录
- **WHEN** 解析到视频 URL 或视频链接
- **THEN** 创建 Asset 记录，包含 `asset_type="video"`、`original_uri`、`storage_uri=null`、`status="pending"` 和来源元素信息
- **AND** 阶段 1 不强制下载或理解视频内容

### Requirement: 处理递归嵌入文档并设置边界
系统 SHALL 递归解析嵌入文档至可配置的最大深度，并支持去重。

#### Scenario: 深度限制内递归解析
- **WHEN** 文档 A 嵌入文档 B，文档 B 嵌入文档 C，max_depth=3
- **THEN** 三个文档全部被解析，每个 Document 的 `parent_doc_id` 和 `root_doc_id` 正确指向文档 A

#### Scenario: 超出最大深度
- **WHEN** 文档 A 在深度 3 处嵌入文档 B，max_depth=3
- **THEN** 文档 B 不被递归解析，其 Document 记录标记 `metadata.skipped_reason="max_depth_exceeded"`

#### Scenario: 重复文档跳过
- **WHEN** 同一文档（相同 `source_hash`）在递归链路中遇到两次
- **THEN** 重复文档被跳过，标记 `metadata.skipped_reason="duplicated_document"`

#### Scenario: 外部资源阶段 1 仅识别关联
- **WHEN** 文档包含图片、视频或附件链接
- **THEN** 系统创建 Asset 并与 ParsedElement 关联
- **AND** 阶段 1 不要求下载到 MinIO、不要求生成 `storage_uri`，后续资源处理可异步补齐
