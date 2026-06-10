# Document Ingestion

## Purpose

将 Markdown/TXT 文档解析为结构化元素树（ParsedElement），创建 Document 和 Asset 记录，并递归处理嵌入文档。本次更新：Document 新增 `category` 字段，入库请求模型移除内联 `content`。

> 同步自 change `align-data-model-and-api-with-updated-design`。

## MODIFIED Requirements

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

## ADDED Requirements

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
