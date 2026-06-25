## ADDED Requirements

### Requirement: Asset 文件按内容寻址存储

系统 SHALL 新增 `make_asset_key(content_hash)` 函数，为 Asset 文件生成内容寻址的 MinIO object key，格式为 `{hash_hex[:2]}/{hash_hex}`。保留 `make_minio_key(doc_id, file_name, asset_id)` 函数用于文档文件上传。

#### Scenario: 生成 Asset 存储 key

- **WHEN** 调用 `make_asset_key("sha256:a1b2c3d4e5f6...")`
- **THEN** 返回 `"a1/a1b2c3d4e5f6..."`

#### Scenario: 文档文件上传使用现有 key 格式

- **WHEN** 上传文档原始文件到 kb-input bucket
- **THEN** 使用 `make_minio_key(doc_id, file_name)` 生成 key
- **AND** key 格式为 `{doc_id[:2]}/{doc_id}/{file_name}`

### Requirement: Asset 删除仅清 PG 元数据

系统 SHALL 在删除 Asset 时仅删除 PostgreSQL 中的元数据记录，不物理删除 MinIO 文件。因 MinIO key 由 content_hash 决定，同内容文件自动共享；孤儿文件由未来定时 GC 回收。

#### Scenario: 删除 Asset 不删 MinIO 文件

- **GIVEN** Asset 的 `storage_uri` 为 `minio://kb-assets/a1/a1b2c3d4...`
- **WHEN** 调用 `MinioAssetStore.delete(asset_id)`
- **THEN** PG 中 Asset 元数据被删除
- **AND** 不调用 MinIO `remove_object`

### Requirement: Asset 上传时 Content-Type 从 metadata 读取

系统 SHALL 在 `MinioAssetStore.put()` 上传 Asset 字节时，优先从 `asset.metadata.get("mime_type")` 获取 Content-Type，无值时才使用 `"application/octet-stream"`。

#### Scenario: metadata 有 mime_type 时使用

- **GIVEN** Asset 的 `metadata["mime_type"]` 为 `"image/png"`
- **WHEN** `MinioAssetStore.put()` 上传文件
- **THEN** MinIO 对象的 Content-Type 设为 `"image/png"`

#### Scenario: metadata 无 mime_type 时回退

- **GIVEN** Asset 的 `metadata` 中不含 `mime_type` 键
- **WHEN** `MinioAssetStore.put()` 上传文件
- **THEN** MinIO 对象的 Content-Type 设为 `"application/octet-stream"`
