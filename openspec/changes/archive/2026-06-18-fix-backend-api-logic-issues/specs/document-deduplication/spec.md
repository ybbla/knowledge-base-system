## MODIFIED Requirements

### Requirement: 上传阶段基于 source_hash 去重

系统 SHALL 在 `POST /api/v1/documents/upload` 接收文件后、写入 MinIO 或本地输入存储前，计算文件 `source_hash` 并查询 PostgreSQL 检查内容是否已存在。命中的活跃文档 SHALL 阻止重复文件写入对象存储。当并发请求导致 `document_repo.create()` 抛出 `DuplicateDocumentError` 时，系统 SHALL 不向对象存储写入文件；若文件已在上层调用中被写入，系统 SHALL 清理已写入的孤儿文件。

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

#### Scenario: 并发上传相同文件导致竞态写冲突
- **GIVEN** 两个并发请求上传相同内容的文件（`source_hash` 相同）
- **WHEN** 一个请求已创建 Document 记录，另一个请求的 `document_repo.create()` 因唯一索引冲突抛出 `DuplicateDocumentError`
- **THEN** 系统 SHALL 返回 `DOCUMENT_DUPLICATE` 错误（HTTP 409）
- **AND** 系统 SHALL NOT 留下无关联 Document 的孤儿文件
