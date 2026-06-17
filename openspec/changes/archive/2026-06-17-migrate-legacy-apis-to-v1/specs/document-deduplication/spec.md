## MODIFIED Requirements

### Requirement: 上传阶段基于 source_hash 去重
系统 SHALL 在 `POST /api/v1/documents/upload` 接收文件后、写入 MinIO 或本地输入存储前，计算文件 `source_hash` 并查询 PostgreSQL 检查内容是否已存在。命中的活跃文档 SHALL 阻止重复文件写入对象存储。

#### Scenario: 上传已存在的文件
- **GIVEN** `documents` 表中存在相同 `source_hash` 且 `status='active'` 的文档
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 上传相同内容的文件
- **THEN** 系统 SHALL 返回 `200 OK`
- **AND** 响应 `data.duplicate` SHALL 为 `true`
- **AND** 响应 `data.existing_doc_id` SHALL 指向已有文档
- **AND** 系统 SHALL NOT 将该文件再次写入 MinIO 或本地输入存储

#### Scenario: 上传新文件
- **GIVEN** `source_hash` 在 `documents` 表中不存在活跃匹配行
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 上传文件
- **THEN** 系统 SHALL 正常写入输入存储
- **AND** 响应 SHALL 包含 `source_uri`
- **AND** 响应 `data.duplicate` SHALL 为 `false`

#### Scenario: 上传与已失败文档相同内容的文件
- **GIVEN** `source_hash` 仅匹配 `status='failed'` 或 `status='deleted'` 的文档
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 上传相同内容的文件
- **THEN** 系统 SHALL 允许上传并创建新的文档记录
- **AND** 响应 `data.duplicate` SHALL 为 `false`

### Requirement: 入库阶段基于 source_hash 去重
系统 SHALL 在 v1 文档创建和上传创建阶段基于 `source_hash` 查询 PostgreSQL，阻止 `status='active'` 的重复文档进入入库管道；对已有文档执行 `POST /api/v1/documents/{doc_id}/ingest` 时 SHALL 使用该文档当前记录，不再按 hash 创建新文档。

#### Scenario: 创建并入库已存在的活跃文档
- **GIVEN** 已存在相同 `source_hash` 且 `status='active'` 的文档
- **WHEN** 客户端请求 `POST /api/v1/documents?ingest_after_create=true` 创建新文档
- **THEN** 系统 SHALL 返回 `DOCUMENT_DUPLICATE`
- **AND** 系统 SHALL NOT 创建新的入库任务

#### Scenario: 创建并入库已失败文档的相同内容
- **GIVEN** `source_hash` 匹配到 `status='failed'` 或 `status='deleted'` 的文档
- **WHEN** 客户端请求 `POST /api/v1/documents?ingest_after_create=true`
- **THEN** 系统 SHALL 允许创建新的 Document 记录
- **AND** 系统 SHALL 按 `ingest_after_create` 提交入库任务

#### Scenario: 已有文档重新入库绕过新建去重
- **GIVEN** 文档 `doc_xxx` 已存在
- **WHEN** 客户端请求 `POST /api/v1/documents/doc_xxx/ingest?mode=incremental`
- **THEN** 系统 SHALL 使用 `doc_xxx` 当前的 `source_hash` 和 `source_uri` 进入更新流程
- **AND** 系统 SHALL NOT 创建新的 Document 记录
