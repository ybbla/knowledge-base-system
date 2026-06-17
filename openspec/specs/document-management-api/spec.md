# Document Management API

## Purpose

通过 `/api/v1/documents` 提供文档（Document）的完整 CRUD、状态治理、入库触发和聚合统计能力，面向前端管理台和运维工具。

> 同步自 change `implement-api-improvement-plan`，日期 2026-06-17。

## Requirements

### Requirement: 文档列表支持分页、筛选和展示统计
系统 SHALL 通过 `GET /api/v1/documents` 返回分页文档列表，并支持按关键词、分类、状态、来源类型、父文档、根文档、入库任务和时间范围筛选。

#### Scenario: 按分类和状态查询文档
- **GIVEN** 系统中存在多个分类和状态的文档
- **WHEN** 客户端请求 `GET /api/v1/documents?category=设备维护&status=active&page=1&page_size=20`
- **THEN** 系统返回分类为 `设备维护` 且状态为 `active` 的文档分页列表
- **AND** 响应 `meta` 包含 `page`、`page_size` 和 `total`

#### Scenario: 文档列表包含前端展示统计
- **GIVEN** 文档已完成入库并生成解析元素、知识块和资源
- **WHEN** 客户端请求文档列表
- **THEN** 每个文档条目 SHALL 包含 `chunk_count`、`element_count`、`asset_count` 和 `index_summary`

#### Scenario: 空结果返回统一结构
- **GIVEN** 没有文档匹配查询条件
- **WHEN** 客户端请求文档列表
- **THEN** 系统返回 `data=[]`
- **AND** `meta.total` 为 `0`
- **AND** `error` 为 `null`

### Requirement: 文档记录可被创建
系统 SHALL 通过 `POST /api/v1/documents` 创建 Document 记录，并允许客户端选择是否创建后立即触发入库。

#### Scenario: 创建文档但不立即入库
- **WHEN** 客户端提交 `title`、`source_type`、`source_uri`、`source_hash`、`category` 和 `metadata`
- **THEN** 系统创建状态为 `pending` 的 Document
- **AND** 返回新文档的 `doc_id`、`status` 和 `version`

#### Scenario: 创建后立即入库
- **WHEN** 客户端提交文档创建请求且 `ingest_after_create=true`
- **THEN** 系统创建 Document
- **AND** 系统提交入库任务
- **AND** 响应包含 `ingest_job_id`

#### Scenario: 创建重复来源文档
- **GIVEN** 已存在相同 `source_hash` 的活跃文档
- **WHEN** 客户端创建新文档
- **THEN** 系统返回冲突错误
- **AND** 错误 `code` 为 `DOCUMENT_DUPLICATE`

### Requirement: 文档详情返回聚合信息
系统 SHALL 通过 `GET /api/v1/documents/{doc_id}` 返回文档基础字段、入库状态、统计信息、子文档信息和元数据。

#### Scenario: 查询存在的文档详情
- **GIVEN** 文档 `doc_xxx` 存在
- **WHEN** 客户端请求 `GET /api/v1/documents/doc_xxx`
- **THEN** 响应 SHALL 包含 Document 的基础字段
- **AND** 响应 SHALL 包含 `chunk_count`、`element_count`、`asset_count` 和 `index_summary`

#### Scenario: 查询不存在的文档详情
- **GIVEN** 文档 `doc_missing` 不存在
- **WHEN** 客户端请求 `GET /api/v1/documents/doc_missing`
- **THEN** 系统返回 404
- **AND** 错误 `code` 为 `DOCUMENT_NOT_FOUND`

### Requirement: 文档可被更新并使用乐观锁
系统 SHALL 通过 `PATCH /api/v1/documents/{doc_id}` 更新文档标题、分类、状态和元数据，并使用 `expected_version` 防止并发覆盖。

#### Scenario: 使用正确版本更新文档
- **GIVEN** 文档当前 `version=2`
- **WHEN** 客户端提交 `expected_version=2` 并更新标题或分类
- **THEN** 系统保存更新
- **AND** 文档版本递增

#### Scenario: 使用过期版本更新文档
- **GIVEN** 文档当前 `version=3`
- **WHEN** 客户端提交 `expected_version=2`
- **THEN** 系统返回 409
- **AND** 错误 `code` 为 `DOCUMENT_VERSION_CONFLICT`

#### Scenario: 更新来源字段提示需要重新入库
- **WHEN** 客户端更新 `source_uri` 或 `source_hash`
- **THEN** 系统保存来源变更
- **AND** 响应 SHALL 表明该文档需要重新入库或重新索引

### Requirement: 文档删除和恢复使用软删除
系统 SHALL 通过 `DELETE /api/v1/documents/{doc_id}` 将文档软删除，并通过 `POST /api/v1/documents/{doc_id}/restore` 恢复文档。

#### Scenario: 删除文档
- **GIVEN** 文档状态为 `active`
- **WHEN** 客户端请求删除文档
- **THEN** 系统将 Document 状态设置为 `deleted`
- **AND** 系统将该文档下活跃 KnowledgeChunk 状态设置为 `deleted`
- **AND** 系统同步检索索引中的知识块状态

#### Scenario: 恢复文档
- **GIVEN** 文档状态为 `deleted`
- **WHEN** 客户端请求恢复文档
- **THEN** 系统将 Document 状态恢复为 `active`
- **AND** 系统按恢复策略恢复或提示恢复该文档下的 KnowledgeChunk

### Requirement: 文档可触发入库动作
系统 SHALL 通过 `POST /api/v1/documents/{doc_id}/ingest` 对指定文档触发入库、增量更新或强制重建。

#### Scenario: 对已有文档触发增量入库
- **GIVEN** 文档 `doc_xxx` 存在
- **WHEN** 客户端提交 `mode=incremental`
- **THEN** 系统提交入库任务
- **AND** 响应包含 `job_id` 和 `doc_id`

#### Scenario: 对不存在文档触发入库
- **GIVEN** 文档不存在
- **WHEN** 客户端请求文档入库
- **THEN** 系统返回 404
- **AND** 错误 `code` 为 `DOCUMENT_NOT_FOUND`
