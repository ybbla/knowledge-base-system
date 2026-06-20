# Document Management API (Delta)

## MODIFIED Requirements

### Requirement: 文档列表支持分页、筛选和展示统计
系统 SHALL 通过 `GET /api/v1/documents` 返回分页文档列表，并支持按关键词、分类、状态、来源类型、父文档、根文档和时间范围筛选。当后端为内存模式且无法支持某些高级筛选参数时，系统 SHALL 在响应 `meta` 中标注未应用的筛选参数。

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

#### Scenario: 内存模式下不支持的筛选参数被标注
- **GIVEN** 后端为内存模式
- **WHEN** 客户端请求包含 `source_type`、`parent_doc_id`、`root_doc_id`、`sort_by` 等内存后端不支持的参数
- **THEN** 系统 SHALL 仍返回匹配基础筛选（关键词、分类、状态）的结果
- **AND** 响应 `meta` SHALL 包含 `unsupported_filters` 字段列出未应用的参数名

### Requirement: 文档文件可通过 v1 上传并创建
系统 SHALL 通过 `POST /api/v1/documents/upload` 接收 multipart 文件上传，计算 `source_hash`，保存文件到配置的输入存储，创建 Document 记录，并立即提交入库任务。上传时 SHALL 检测同名文件并提示是否更新。

#### Scenario: 上传文件并立即入库
- **GIVEN** 客户端选择一个尚未入库的文件
- **WHEN** 客户端请求 `POST /api/v1/documents/upload` 并提交 `file`、`title` 和 `category`
- **THEN** 系统 SHALL 保存文件并创建 Document
- **AND** 系统 SHALL 提交入库任务
- **AND** 响应 `data` SHALL 包含 `doc_id`、`source_uri` 和 `source_hash`

#### Scenario: 上传重复文件
- **GIVEN** 已存在相同 `source_hash` 且状态为 `active` 的文档
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 上传相同内容的文件
- **THEN** 系统 SHALL 返回重复文档信息
- **AND** 响应 `data.duplicate` SHALL 为 `true`
- **AND** 响应 `data.existing_doc_id` SHALL 指向已有文档

#### Scenario: 上传同名但不同内容的文件（单个匹配）
- **GIVEN** 已存在一个同名的活跃文档
- **GIVEN** 文件内容不重复（`source_hash` 不同）
- **WHEN** 客户端上传文件
- **THEN** 系统返回 `suggested_replace=true`
- **AND** 返回 `suggested_doc_id` 和 `suggested_doc_title`

#### Scenario: 确认更新同名文件
- **GIVEN** 已存在同名的活跃文档
- **WHEN** 客户端上传文件并指定 `replace_doc_id` 和 `confirm_replace=true`
- **THEN** 系统软删除旧文档
- **AND** 系统软删除旧文档的知识块并从索引移除
- **AND** 系统创建新文档，`previous_doc_id` 指向旧文档

### Requirement: 文档记录可被创建
系统 SHALL 通过 `POST /api/v1/documents` 创建 Document 记录，并允许客户端选择是否创建后立即触发入库。该接口用于后端可访问的 `source_uri`，文件上传 SHALL 使用 `POST /api/v1/documents/upload`。

#### Scenario: 创建文档但不立即入库
- **GIVEN** 客户端已有后端可访问的 `source_uri`
- **WHEN** 客户端提交 `title`、`source_type`、`source_uri`、`source_hash`、`category` 和 `metadata`
- **THEN** 系统 SHALL 创建 Document
- **AND** 响应 SHALL 返回新文档的 `doc_id`、`status` 和 `version`

#### Scenario: 创建后立即入库
- **GIVEN** 客户端已有后端可访问的 `source_uri`
- **WHEN** 客户端提交文档创建请求且 `ingest_after_create=true`
- **THEN** 系统 SHALL 创建 Document
- **AND** 系统 SHALL 提交入库任务

#### Scenario: 创建重复来源文档
- **GIVEN** 已存在相同 `source_hash` 的活跃文档
- **WHEN** 客户端创建新文档
- **THEN** 系统 SHALL 返回冲突错误
- **AND** 错误 `code` SHALL 为 `DOCUMENT_DUPLICATE`

### Requirement: 文档详情返回聚合信息
系统 SHALL 通过 `GET /api/v1/documents/{doc_id}` 返回文档基础字段、入库状态、统计信息、子文档信息和元数据。

#### Scenario: 查询存在的文档详情
- **GIVEN** 文档 `doc_xxx` 存在
- **WHEN** 客户端请求 `GET /api/v1/documents/doc_xxx`
- **THEN** 响应 SHALL 包含 Document 的基础字段
- **AND** 响应 SHALL 包含 `chunk_count`、`element_count`、`asset_count` 和 `index_summary`
- **AND** 响应 SHALL 包含 `previous_doc_id` 和 `error_message`

#### Scenario: 查询不存在的文档详情
- **GIVEN** 文档 `doc_missing` 不存在
- **WHEN** 客户端请求 `GET /api/v1/documents/doc_missing`
- **THEN** 系统返回 404
- **AND** 错误 `code` 为 `DOCUMENT_NOT_FOUND`

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
- **AND** 系统按恢复策略恢复该文档下的 KnowledgeChunk

## REMOVED Requirements

### Requirement: 文档可触发入库动作
**Reason**: 不再需要单独的重新处理接口，用户可以重新上传文件来达到相同效果
**Migration**: 用户如需重新处理文档，可通过上传更新或直接重新上传文件

### Requirement: 文档可被更新并使用乐观锁
**Reason**: 乐观锁机制整体移除。更新流程已改为"软删除旧文档 + 创建新文档"，不再有原地更新的并发冲突场景。`version` 字段保留用于展示版本号，但不再用于并发控制。
**Migration**: `PATCH /api/v1/documents/{doc_id}` 端点一并移除。元数据变更（如标题、分类）如有需要可后续单独设计轻量级编辑接口。

### Requirement: VersionConflictError 异常类型
**Reason**: 随乐观锁机制移除。
**Migration**: `VersionConflictError` 类从 `app/core/errors.py` 中删除。

## ADDED Requirements

### Requirement: 文档版本历史查看
系统 SHALL 通过 `GET /api/v1/documents/{doc_id}/history` 提供文档版本历史查看功能。

#### Scenario: 查询文档版本历史
- **GIVEN** 文档 `doc_xxx` 存在
- **WHEN** 客户端请求 `GET /api/v1/documents/doc_xxx/history`
- **THEN** 系统返回版本历史列表
- **AND** 列表按时间倒序排列
- **AND** 每个条目包含 `doc_id`、`title`、`version`、`status` 和 `created_at`

#### Scenario: 查询不存在文档的版本历史
- **GIVEN** 文档不存在
- **WHEN** 客户端请求版本历史
- **THEN** 系统返回 404 错误
