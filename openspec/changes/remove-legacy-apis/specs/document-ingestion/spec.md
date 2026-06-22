# Document Ingestion (Delta)

## REMOVED Requirements

### Requirement: 旧版上传和入库接口

**Reason**: v1 接口（`POST /api/v1/documents/upload`、`POST /api/v1/documents/{doc_id}/ingest`）已完整覆盖功能，旧版接口标记 deprecated 超过 2 周。

**Migration**: 使用 `/api/v1/documents/upload` 替代 `/upload` + `/ingest`；使用 `/api/v1/search` 替代 `/search`；使用 `/api/v1/documents` 替代 `/documents`。

## ADDED Requirements

### Requirement: 上传工具函数独立模块

系统 SHALL 将 `_hash_upload()`、`save_upload_file()`、`DEFAULT_CATEGORY` 等工具函数维护在 `app/api/upload_utils.py` 中，供 v1 接口复用。

#### Scenario: v1 上传接口正常使用工具函数

- **GIVEN** 用户通过 `POST /api/v1/documents/upload` 上传文件
- **WHEN** v1 接口调用 `upload_utils._hash_upload(file)` 和 `upload_utils.save_upload_file(file)`
- **THEN** 行为与迁移前完全一致
- **AND** 文件写入 MinIO，返回 `source_uri` 和 `source_hash`
