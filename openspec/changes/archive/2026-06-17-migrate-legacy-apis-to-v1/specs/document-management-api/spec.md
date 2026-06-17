## ADDED Requirements

### Requirement: 文档文件可通过 v1 上传并创建
系统 SHALL 通过 `POST /api/v1/documents/upload` 接收 multipart 文件上传，计算 `source_hash`，保存文件到配置的输入存储，创建 Document 记录，并允许客户端通过 `ingest_after_create` 选择是否立即提交入库任务。

#### Scenario: 上传文件并立即入库
- **GIVEN** 客户端选择一个尚未入库的文件
- **WHEN** 客户端请求 `POST /api/v1/documents/upload?ingest_after_create=true&mode=incremental` 并提交 `file`、`title` 和 `category`
- **THEN** 系统 SHALL 保存文件并创建 Document
- **AND** 系统 SHALL 提交入库任务
- **AND** 响应 `data` SHALL 包含 `doc_id`、`source_uri`、`source_hash` 和 `ingest_job_id`

#### Scenario: 上传文件但不立即入库
- **GIVEN** 客户端选择一个尚未入库的文件
- **WHEN** 客户端请求 `POST /api/v1/documents/upload?ingest_after_create=false`
- **THEN** 系统 SHALL 保存文件并创建 Document
- **AND** 系统 SHALL NOT 提交入库任务
- **AND** 响应 `data.ingest_job_id` SHALL 为空或不存在

#### Scenario: 上传重复文件
- **GIVEN** 已存在相同 `source_hash` 且状态为 `active` 的文档
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 上传相同内容的文件
- **THEN** 系统 SHALL 返回重复文档信息
- **AND** 响应 `data.duplicate` SHALL 为 `true`
- **AND** 响应 `data.existing_doc_id` SHALL 指向已有文档

## MODIFIED Requirements

### Requirement: 文档记录可被创建
系统 SHALL 通过 `POST /api/v1/documents` 创建 Document 记录，并允许客户端选择是否创建后立即触发入库。该接口用于后端可访问的 `source_uri`，文件上传 SHALL 使用 `POST /api/v1/documents/upload`。

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

### Requirement: 文档可触发入库动作
系统 SHALL 通过 `POST /api/v1/documents/{doc_id}/ingest` 对指定文档触发入库、增量更新或强制重建，并返回可被入库任务页面展示和轮询的任务信息。

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
