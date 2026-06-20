# Document Ingestion (Delta)

## MODIFIED Requirements

### Requirement: 解析过程中创建 Document 和 Asset 记录
系统 SHALL 在解析时为文档创建 Document 记录（含 `category`），为每个识别到的资源创建 Asset 记录。

#### Scenario: 创建 Document 记录
- **WHEN** 文档提交解析
- **THEN** 创建 Document 记录，包含 `doc_id`、`title`、`source_type`、`source_uri`、`source_hash`、`version=1`、`status="processing"`、`category` 和时间戳
- **AND** 若 `category` 未指定，默认值为 `"通用"`
- **AND** 若文档来自嵌入文档，记录 `parent_doc_id`、`root_doc_id` 和 `metadata.embed_path`
- **AND** 若文档为更新版本，记录 `previous_doc_id`

#### Scenario: 为图片创建 Asset 记录
- **WHEN** 解析到图片链接
- **THEN** 创建 Asset 记录，包含 `asset_id`、`doc_id`、`source_element_id`、`asset_type="image"`、`original_uri`、`storage_uri=null`、`content_hash`、`status="pending"`、`extracted_text=null`、`error_message=null` 和 `created_at`/`updated_at`

### Requirement: 状态流转简化
文档状态 SHALL 从 `processing` 开始，成功后变为 `active`，失败后变为 `failed`。移除 `pending` 状态。

#### Scenario: 文档初始状态
- **WHEN** 文档被创建
- **THEN** 初始状态为 `processing`

#### Scenario: 入库成功
- **WHEN** 文档入库成功
- **THEN** 状态变为 `active`

#### Scenario: 入库失败
- **WHEN** 文档入库失败
- **THEN** 状态变为 `failed`
- **AND** `error_message` 记录失败原因

## REMOVED Requirements

### Requirement: ChunkStatus.superseded
**Reason**: 不再需要 superseded 状态，旧版本知识块直接用 deleted 状态
**Migration**: 历史数据中的 superseded 状态可转换为 deleted 状态
