# File Upload (Delta)

## MODIFIED Requirements

### Requirement: 文件上传并写入本地存储

系统 SHALL 提供 `/api/v1/documents/upload` 端点，接收 multipart/form-data 文件并写入存储后端。当 MinIO 可用（`MINIO_ENABLED=true`）时写入 MinIO `kb-input` Bucket；当 MinIO 未启用或不可用时写入本地磁盘 `data/uploads/` 目录。上传时 SHALL 检测内容重复（`source_hash`）和同名文件（按 `title`），并支持确认更新参数。

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

#### Scenario: 上传文件到本地磁盘（MinIO 不可用时回退）
- **GIVEN** MinIO 已启用但上传初始化或写入失败
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 提交文件
- **THEN** 系统回退写入 `data/uploads/` 目录
- **AND** 响应返回 `source_uri`、`source_hash`、`file_name` 和 `size`

#### Scenario: 上传时未指定 title
- **WHEN** 客户端仅提交 `file` 未提供 `title`
- **THEN** 返回的响应中 title 为文件名（不含扩展名）

#### Scenario: 上传时未指定 category
- **WHEN** 客户端仅提交 `file` 未提供 `category`
- **THEN** category 使用默认值 `"通用"`

#### Scenario: 文件存储目录自动创建
- **GIVEN** MinIO 未启用且 `data/uploads/` 目录不存在
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 提交文件
- **THEN** 系统自动创建目录，文件写入成功

#### Scenario: MinIO 存储路径自动分片
- **GIVEN** MinIO 已启用且可用
- **WHEN** 文件上传到 MinIO 时
- **THEN** 存储路径按 `{doc_id[:2]}/{doc_id}/{file_name}` 分片，确保单目录文件数可控

#### Scenario: 检测到同名文件提示更新
- **GIVEN** 已存在同名的活跃文档
- **GIVEN** 文件内容不重复
- **WHEN** 客户端上传文件
- **THEN** 响应返回 `suggested_replace=true`
- **AND** 响应包含 `suggested_doc_id` 和 `suggested_doc_title`

#### Scenario: 确认更新同名文件
- **GIVEN** 已存在同名的活跃文档
- **WHEN** 客户端上传文件并指定 `replace_doc_id` 和 `confirm_replace=true`
- **THEN** 系统软删除旧文档及知识块
- **AND** 系统创建新文档并开始入库
