## Why

4 个旧版 API 文件（`app/api/upload.py`、`ingest.py`、`documents.py`、`search.py`）标记 deprecated 已久，v1 接口已完整覆盖其功能。其中 `upload.py` 的工具函数（`_hash_upload()`、`save_upload_file()`、`DEFAULT_CATEGORY`）仍被 v1 复用，阻碍了解耦改造。本次变更迁移被复用的工具函数到独立模块，删除 4 个旧版 API 文件及其路由注册，清理测试中的旧端点调用。

这是 `decouple-content-from-parser` 的前置变更——旧版 `ingest.py` 的调用方式（`ingestion_pipeline.ingest(doc)` 无 raw_content）与方案 B 新签名不兼容，必须先移除。

## What Changes

- **新建 `app/api/upload_utils.py`**：迁移 `_hash_upload()`、`save_upload_file()`、`DEFAULT_CATEGORY`、`CHUNK_SIZE`、`MINIO_PART_SIZE`
- **删除 4 个旧版 API 文件**：`app/api/upload.py`、`app/api/ingest.py`、`app/api/documents.py`、`app/api/search.py`
- **`main.py`**：移除 4 个旧路由注册
- **`app/api/v1/documents.py`**：import 从 `app.api.upload` 改为 `app.api.upload_utils`
- **测试清理**：删除或改写 `test_document_dedup.py`、`test_search_pipeline.py`、`test_documents_api.py` 中直接调旧端点的测试

## Capabilities

### Modified Capabilities
- `document-ingestion`: 旧版 `/upload`、`/ingest`、`/documents`、`/search` 路由移除；工具函数迁至 `upload_utils.py`

## Impact

- **删除文件**：`app/api/upload.py`、`app/api/ingest.py`、`app/api/documents.py`、`app/api/search.py`
- **新增文件**：`app/api/upload_utils.py`
- **修改文件**：`app/main.py`、`app/api/v1/documents.py`、`tests/test_document_dedup.py`、`tests/test_search_pipeline.py`、`tests/integration/test_documents_api.py`
- **BREAKING**：旧版 `/upload`、`/ingest`、`/documents`、`/search` 端点移除
- **依赖**：无
