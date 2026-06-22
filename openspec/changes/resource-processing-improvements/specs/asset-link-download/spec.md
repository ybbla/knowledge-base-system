# Asset Link Download

## Purpose

定义外部链接资源（image_link、video_link、document_link）的 HTTP 下载与 MinIO 上传流程，确保所有链接类型资源都能被持久化到对象存储。

## ADDED Requirements

### Requirement: 外部链接资源 HTTP 下载

系统 SHALL 对 `asset_type` 为 `image_link`、`video_link`、`document_link` 的 Asset 执行 HTTP 下载，获取原始字节数据。

#### Scenario: 成功下载

- **WHEN** Asset 的 `original_uri` 为 HTTP/HTTPS URL
- **THEN** 系统发送 GET 请求，超时时间 30 秒
- **AND** 若响应状态码为 200，则将响应体字节传给后续处理步骤

#### Scenario: 下载超时

- **WHEN** HTTP 请求在 30 秒内未完成
- **THEN** 系统标记 Asset 为 `status=failed`，`error_message` 记录 `download_timeout`
- **AND** 不阻塞其他 Asset 的处理

#### Scenario: 下载返回非 200

- **WHEN** HTTP 响应状态码不为 200
- **THEN** 系统标记 Asset 为 `status=failed`，`error_message` 记录 `download_failed: HTTP {status_code}`
- **AND** 不阻塞其他 Asset 的处理

#### Scenario: 下载网络错误

- **WHEN** HTTP 请求因 DNS 解析失败、连接拒绝等网络错误而失败
- **THEN** 系统标记 Asset 为 `status=failed`，`error_message` 记录具体错误原因
- **AND** 不阻塞其他 Asset 的处理

### Requirement: 下载后上传 MinIO

系统 SHALL 在下载成功后，将资源字节上传到 MinIO `kb-assets` Bucket，并更新 Asset 的 `storage_uri`。

#### Scenario: 上传成功

- **WHEN** 资源字节下载成功
- **THEN** 系统将字节上传到 MinIO，路径为 `kb-assets/{doc_id[:2]}/{doc_id}/{asset_id}/{file_name}`
- **AND** Asset 的 `storage_uri` 更新为 `minio://kb-assets/{doc_id[:2]}/{doc_id}/{asset_id}/{file_name}`

#### Scenario: 上传失败

- **WHEN** MinIO 上传出错
- **THEN** Asset 标记为 `status=failed`，`error_message` 记录详细错误
- **AND** 不阻塞其他 Asset 的处理

### Requirement: document_link 下载后触发子文档入库

系统 SHALL 对 `document_link` 类型的 Asset 执行 HTTP 下载，上传到 MinIO `kb-input` Bucket（与用户上传相同路径），然后创建子 Document 并触发完整入库流水线。

#### Scenario: 文档链接下载成功并触发入库

- **WHEN** Asset 的 `asset_type` 为 `document_link` 且 HTTP 下载成功
- **THEN** 系统将文件字节上传到 MinIO `kb-input` Bucket，路径为 `{doc_id[:2]}/{child_doc_id}/{file_name}`
- **AND** 创建子 Document：`title` 从 URL 文件名推断，`source_type` 根据后缀推断，`source_uri` 为 MinIO 路径，`source_hash` 为 sha256(内容)，`parent_doc_id` 为当前文档，`root_doc_id` 为当前文档的根文档
- **AND** 调用 `document_repo.create(child_doc)` 持久化子文档
- **AND** 调用 `ingestion_pipeline.ingest(child_doc, raw_content=下载内容)` 触发完整入库流水线（解析 → 语义抽取 → 双路索引）
- **AND** 子文档入库成功后，Asset 的 `storage_uri` 更新为子文档的 `source_uri`

#### Scenario: 文档链接后缀无法识别

- **WHEN** document_link 的 URL 后缀不在支持格式列表中（pdf/docx/xlsx/pptx/html/md/txt）
- **THEN** Asset 标记为 `status=failed`，`error_message` 记录 `unsupported_document_type`
- **AND** 不创建子文档，不触发入库

#### Scenario: 文档链接下载失败不影响主文档入库

- **WHEN** document_link 下载失败
- **THEN** Asset 标记为 `status=failed`，`error_message` 记录失败原因
- **AND** 主文档的入库流程继续正常执行
- **AND** 不创建子文档

#### Scenario: 子文档入库失败不影响主文档

- **WHEN** 子文档入库流水线执行失败
- **THEN** 子文档状态为 `failed`，`error_message` 记录失败原因
- **AND** 主文档入库流程继续正常执行
