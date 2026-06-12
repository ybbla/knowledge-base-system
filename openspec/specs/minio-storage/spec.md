# MinIO Storage

## Purpose

将文件上传和 Asset 存储从本地磁盘迁移至可选的 MinIO 对象存储，支持文件上传、下载、删除和 presigned URL 生成，并实现 `MinioAssetStore(AssetStore)` 适配抽象接口。

> 新建自 change `phase-3-milvus-minio`，日期 2026-06-12。

## Requirements

### Requirement: MinIO Bucket 自动创建

系统 SHALL 在首次启动时自动创建 `kb-input`（原始文档）和 `kb-assets`（资源文件）两个 Bucket，不存在时创建，已存在时直接使用。

#### Scenario: 首次启动自动建 Bucket

- **WHEN** MinIO 连接可用且目标 Bucket 不存在
- **THEN** 系统自动创建 Bucket（私有访问策略），并记录 INFO 日志

#### Scenario: Bucket 已存在时跳过

- **WHEN** MinIO 连接可用且目标 Bucket 已存在
- **THEN** 系统直接使用已有 Bucket，不报错

#### Scenario: MinIO 不可用时回退

- **WHEN** `MINIO_ENABLED=true` 但 MinIO 连接失败
- **THEN** 系统记录 ERROR 日志，回退到本地磁盘或 MemoryAssetStore

### Requirement: 文件上传写入 MinIO

系统 SHALL 将 `/upload` 端点接收的文件写入 MinIO `kb-input` Bucket，按 `{doc_id[:2]}/{doc_id}/{file_name}` 路径组织。

#### Scenario: 上传文件到 MinIO

- **WHEN** 客户端通过 `POST /upload` 提交文件
- **THEN** 文件流直接写入 MinIO `kb-input` Bucket，路径为 `{doc_id[:2]}/{doc_id}/{file_name}`
- **AND** 返回 `source_uri` 格式为 `minio://kb-input/{doc_id[:2]}/{doc_id}/{file_name}`

#### Scenario: 大文件分片上传

- **WHEN** 文件大小超过 5MB
- **THEN** 系统使用 MinIO SDK 的分片上传能力，避免内存溢出

### Requirement: MinIO 文件操作

系统 SHALL 基于 MinIO SDK 实现文件的下载、删除和存在性检查。

#### Scenario: 从 MinIO 下载文件

- **WHEN** 入库管道需要读取 `source_uri` 指向的文档内容
- **THEN** 系统解析 `minio://bucket/path` URI，通过 MinIO SDK `get_object()` 获取文件流

#### Scenario: 从 MinIO 删除文件

- **WHEN** 文档被删除或其 Asset 被清理
- **THEN** 系统通过 MinIO SDK `remove_object()` 删除对应文件

### Requirement: Presigned URL 生成

系统 SHALL 为 MinIO 中存储的文件生成有时效的 presigned GET URL，供检索结果中的 `asset_refs` 返回，前端可直接渲染。

#### Scenario: 检索结果返回可渲染资源 URL

- **WHEN** 检索响应构建 `asset_refs` 时
- **THEN** 系统为每个关联 Asset 的 `storage_uri` 生成 presigned URL（默认有效期 1 小时，可配置），填入 `storage_uri` 字段

#### Scenario: Presigned URL 过期

- **WHEN** presigned URL 超过有效期
- **THEN** URL 不可访问，前端需重新请求检索 API 获取新 URL

#### Scenario: 非 MinIO Asset 不生成 presigned URL

- **WHEN** Asset 的 `storage_uri` 为 null 或外部 URL（非 `minio://` 前缀）
- **THEN** 直接返回原始 `storage_uri` 或 `original_uri`，不生成 presigned URL

### Requirement: MinioAssetStore 适配 AssetStore 接口

系统 SHALL 实现 `MinioAssetStore(AssetStore)` 类，匹配 `put()`、`get()`、`delete()` 接口契约，使 `IngestionPipeline` 和 `RetrievalPipeline` 无需修改即可使用对象存储后端。

#### Scenario: MinioAssetStore.put() 存储 Asset 元数据

- **WHEN** 调用 `put(asset)`
- **THEN** Asset 元数据写入 PostgreSQL（`BACKEND=postgres`）或内存（`BACKEND=memory`），同时将关联的文件上传到 MinIO

#### Scenario: MinioAssetStore.get() 返回 Asset 含可渲染 URL

- **WHEN** 调用 `get(asset_id)`
- **THEN** 返回的 Asset 对象中 `storage_uri` 已替换为 presigned URL
