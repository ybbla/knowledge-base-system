## MODIFIED Requirements

### Requirement: 文件上传写入 MinIO
系统 SHALL 将 `POST /api/v1/documents/upload` 端点接收的文件写入 MinIO `kb-input` Bucket，按 `{doc_id[:2]}/{doc_id}/{file_name}` 路径组织；旧 `POST /upload` 在兼容期内 MAY 复用相同存储逻辑，但不再作为前端业务入口。

#### Scenario: 上传文件到 MinIO
- **GIVEN** `MINIO_ENABLED=true` 且 MinIO 可用
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 提交文件
- **THEN** 文件流 SHALL 直接写入 MinIO `kb-input` Bucket
- **AND** 路径 SHALL 为 `{doc_id[:2]}/{doc_id}/{file_name}`
- **AND** 响应 SHALL 返回格式为 `minio://kb-input/{doc_id[:2]}/{doc_id}/{file_name}` 的 `source_uri`

#### Scenario: 大文件分片上传
- **GIVEN** 上传文件大小超过 MinIO 单次上传阈值
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 提交该文件
- **THEN** 系统 SHALL 使用 MinIO SDK 的分片上传能力
- **AND** 系统 SHALL 避免将完整文件读入内存

#### Scenario: MinIO 上传失败时回退
- **GIVEN** `MINIO_ENABLED=true` 但 MinIO 写入失败
- **WHEN** 客户端通过 `POST /api/v1/documents/upload` 提交文件
- **THEN** 系统 SHALL 记录错误日志
- **AND** 系统 SHALL 按现有策略回退到本地输入存储或返回可诊断错误
