# Chunk Management API

## Purpose

通过 `/api/v1/chunks` 提供知识块（KnowledgeChunk）的完整 CRUD、状态治理和批量操作能力，面向前端管理台和运维工具。ChunkIndexStatus 已移除，知识块索引通过创建和恢复操作自动触发。

> 同步自 change `implement-api-improvement-plan`，日期 2026-06-17；更新自 change `simplify-status-model`，日期 2026-06-19。

## Requirements

### Requirement: 知识块列表支持分页、筛选和内容摘要

系统 SHALL 通过 `GET /api/v1/chunks` 返回分页知识块列表，并支持按文档、分类、知识类型、业务状态、关键词、是否有关联资源和是否有来源引用筛选。

#### Scenario: 按文档和状态查询知识块
- **GIVEN** 文档 `doc_xxx` 下存在多个状态的知识块
- **WHEN** 客户端请求 `GET /api/v1/chunks?doc_id=doc_xxx&status=deleted&page=1&page_size=20`
- **THEN** 系统仅返回该文档下状态为 `deleted` 的知识块
- **AND** 响应包含分页 `meta`

#### Scenario: 知识块列表包含展示摘要
- **WHEN** 客户端请求知识块列表
- **THEN** 每个知识块条目 SHALL 包含 `content_preview`、`doc_title`、`asset_count` 和 `source_count`
- **AND** 列表条目不必返回完整 `content`

### Requirement: 知识块可被手动创建

系统 SHALL 通过 `POST /api/v1/chunks` 创建 KnowledgeChunk，并允许创建后立即重建索引。

#### Scenario: 创建人工知识块并立即索引
- **WHEN** 客户端提交 `doc_id`、`title`、`content`、`knowledge_type`、`category` 和 `index_after_create=true`
- **THEN** 系统创建 KnowledgeChunk
- **AND** 系统计算 `content_hash`
- **AND** 系统提交该知识块索引
- **AND** `metadata.manual` SHALL 被保留

#### Scenario: 创建缺少文档的知识块
- **GIVEN** 请求中的 `doc_id` 不存在
- **WHEN** 客户端创建知识块
- **THEN** 系统返回 404
- **AND** 错误 `code` 为 `DOCUMENT_NOT_FOUND`

### Requirement: 知识块详情返回完整内容、来源和资源

系统 SHALL 通过 `GET /api/v1/chunks/{chunk_id}` 返回知识块完整内容、所属文档摘要、来源引用、资源引用和元数据。

#### Scenario: 查询知识块详情
- **GIVEN** 知识块存在且包含 `source_refs` 和 `asset_refs`
- **WHEN** 客户端请求知识块详情
- **THEN** 响应 SHALL 包含完整 `content`
- **AND** 响应 SHALL 展开来源引用和资源引用所需的展示字段

#### Scenario: 查询不存在的知识块
- **WHEN** 客户端请求不存在的 `chunk_id`
- **THEN** 系统返回 404
- **AND** 错误 `code` 为 `CHUNK_NOT_FOUND`

### Requirement: 知识块可被更新并保持索引一致

系统 SHALL 通过 `PATCH /api/v1/chunks/{chunk_id}` 更新知识块标题、内容、分类、知识类型、状态、来源引用、资源引用和元数据。

#### Scenario: 更新内容时自动重建索引
- **GIVEN** 知识块当前内容为旧内容
- **WHEN** 客户端提交新的 `content`
- **THEN** 系统重新计算 `content_hash`
- **AND** 系统重新生成 embedding 并重建索引

#### Scenario: 更新状态时同步索引
- **WHEN** 客户端将知识块状态从 `active` 更新为 `deleted`
- **THEN** 系统更新存储中的 KnowledgeChunk 状态
- **AND** 系统从向量索引和 BM25 索引中移除该知识块

### Requirement: 知识块删除和恢复使用软删除

系统 SHALL 通过 `DELETE /api/v1/chunks/{chunk_id}` 将知识块软删除，并通过 `POST /api/v1/chunks/{chunk_id}/restore` 恢复知识块。

#### Scenario: 删除知识块
- **GIVEN** 知识块状态为 `active`
- **WHEN** 客户端请求删除知识块
- **THEN** 系统将状态设置为 `deleted`
- **AND** 检索接口不再返回该知识块

#### Scenario: 恢复知识块
- **GIVEN** 知识块状态为 `deleted`
- **WHEN** 客户端请求恢复知识块
- **THEN** 系统将状态恢复为 `active`
- **AND** 系统触发该知识块重新索引

### Requirement: 知识块支持批量状态操作

系统 SHALL 支持通过 `POST /api/v1/chunks/bulk-status` 对多个知识块执行状态更新、软删除或恢复。

#### Scenario: 批量软删除知识块
- **WHEN** 客户端提交批量删除操作和多个 `chunk_ids`
- **THEN** 系统将这些知识块状态设置为 `deleted`
- **AND** 系统从检索索引中移除这些知识块
