## MODIFIED Requirements

### Requirement: 文档记录可被创建

系统 SHALL 通过 `POST /api/v1/documents` 创建 Document 记录，并允许客户端选择是否创建后立即触发入库。该接口用于后端可访问的 `source_uri`，文件上传 SHALL 使用 `POST /api/v1/documents/upload`。当后端为内存模式（`document_repo` 不可用）且 `ingest_after_create=False` 时，系统 SHALL 在响应 `meta` 中返回 `warning` 提示文档仅在入库后可见。

#### Scenario: 创建文档但不立即入库
- **GIVEN** 客户端已有后端可访问的 `source_uri`
- **WHEN** 客户端提交 `title`、`source_type`、`source_uri`、`source_hash`、`category` 和 `metadata`
- **THEN** 系统 SHALL 创建 Document
- **AND** 响应 SHALL 返回新文档的 `doc_id`、`status` 和 `version`
- **AND** 响应 SHALL NOT 包含新的入库任务 ID

#### Scenario: 创建后立即入库
- **GIVEN** 客户端已有后端可访问的 `source_uri`
- **WHEN** 客户端提交文档创建请求且 `ingest_after_create=true`
- **THEN** 系统 SHALL 创建 Document
- **AND** 系统 SHALL 提交入库任务
- **AND** 响应 SHALL 包含 `ingest_job_id`
- **AND** 响应 SHALL 包含可展示的任务提交状态

#### Scenario: 创建重复来源文档
- **GIVEN** 已存在相同 `source_hash` 的活跃文档
- **WHEN** 客户端创建新文档
- **THEN** 系统 SHALL 返回冲突错误
- **AND** 错误 `code` SHALL 为 `DOCUMENT_DUPLICATE`

#### Scenario: 内存模式下创建文档但不入库
- **GIVEN** 后端为内存模式（`document_repo` 不可用）
- **WHEN** 客户端创建文档且 `ingest_after_create=false`
- **THEN** 系统 SHALL 返回成功响应
- **AND** 响应 `meta` SHALL 包含 `warning` 提示该文档在入库前不可通过列表或详情接口查询

### Requirement: 文档列表支持分页、筛选和展示统计

系统 SHALL 通过 `GET /api/v1/documents` 返回分页文档列表，并支持按关键词、分类、状态、来源类型、父文档、根文档、入库任务和时间范围筛选。当后端为内存模式且无法支持某些高级筛选参数时，系统 SHALL 在响应 `meta` 中标注未应用的筛选参数。

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
- **WHEN** 客户端请求包含 `source_type`、`parent_doc_id`、`root_doc_id`、`ingest_job_id`、`sort_by` 等内存后端不支持的参数
- **THEN** 系统 SHALL 仍返回匹配基础筛选（关键词、分类、状态）的结果
- **AND** 响应 `meta` SHALL 包含 `unsupported_filters` 字段列出未应用的参数名

### Requirement: 文档可触发入库动作

系统 SHALL 通过 `POST /api/v1/documents/{doc_id}/ingest` 对指定文档触发入库、增量更新或强制重建，并返回可被入库任务页面展示和轮询的任务信息。当后端为内存模式时，系统 SHALL 从 chunk_store 中获取已有文档信息来补全 Document 对象的关键字段。

#### Scenario: 对已有文档触发增量入库
- **GIVEN** 文档 `doc_xxx` 存在
- **WHEN** 客户端提交 `mode=incremental`
- **THEN** 系统 SHALL 提交入库任务
- **AND** 响应 `data` SHALL 包含 `job_id`、`doc_id`、`mode` 和任务状态

#### Scenario: 对已有文档触发强制重建
- **GIVEN** 文档 `doc_xxx` 存在
- **WHEN** 客户端提交 `mode=force`
- **THEN** 系统 SHALL 提交强制重建任务
- **AND** 响应 `data.mode` SHALL 为 `force`
- **AND** 新任务 SHALL 重新解析并覆盖该文档的索引结果

#### Scenario: 对不存在文档触发入库
- **GIVEN** 文档不存在
- **WHEN** 客户端请求文档入库
- **THEN** 系统 SHALL 返回 404
- **AND** 错误 `code` SHALL 为 `DOCUMENT_NOT_FOUND`

#### Scenario: 内存模式下对已有文档触发入库
- **GIVEN** 后端为内存模式，文档已有 chunk 在 chunk_store 中
- **WHEN** 客户端请求 `POST /api/v1/documents/{doc_id}/ingest`
- **THEN** 系统 SHALL 从 chunk_store 中获取该文档的 title、source_type、source_hash、category 信息
- **AND** 系统 SHALL 用补全后的 Document 对象提交入库任务
