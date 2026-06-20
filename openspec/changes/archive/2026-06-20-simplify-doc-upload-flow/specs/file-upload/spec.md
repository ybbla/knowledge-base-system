# File Upload (Delta)

## MODIFIED Requirements

### Requirement: 文件上传并写入本地存储
系统 SHALL 提供 `/api/v1/documents/upload` 端点，接收 multipart/form-data 文件并写入存储后端。当 MinIO 可用（`MINIO_ENABLED=true`）时写入 MinIO `kb-input` Bucket；当 MinIO 未启用或不可用时写入本地磁盘 `data/uploads/` 目录。上传时 SHALL 检测同名文件并提示更新。

#### Scenario: 上传 DOCX 文件到 MinIO
- **GIVEN** MinIO 已启用且可用
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 以 multipart/form-data 提交 `file=manual.docx`、`title=产品说明书`、`category=产品使用`
- **THEN** 文件写入 MinIO `kb-input/{doc_id[:2]}/{doc_id}/manual.docx`
- **AND** 响应返回 `source_uri`、`source_hash`（sha256）、`file_name`、`size` 和 `doc_id`

#### Scenario: 上传文件到本地磁盘（MinIO 未启用）
- **GIVEN** MinIO 未启用
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 提交文件
- **THEN** 文件写入 `data/uploads/` 目录
- **AND** 响应返回 `source_uri`、`source_hash`、`file_name`、`size` 和 `doc_id`

#### Scenario: 上传时未指定 title
- **WHEN** 客户端仅提交 `file` 未提供 `title`
- **THEN** 返回的响应中 title 为文件名（不含扩展名）

#### Scenario: 上传时未指定 category
- **WHEN** 客户端仅提交 `file` 未提供 `category`
- **THEN** category 使用默认值 `"通用"`

#### Scenario: 检测到同名文件提示更新
- **GIVEN** 已存在同名的活跃文档
- **GIVEN** 文件内容不重复
- **WHEN** 客户端上传文件
- **THEN** 响应返回 `suggested_replace=true`
- **AND** 响应包含 `suggested_doc_id` 和 `suggested_doc_title`
