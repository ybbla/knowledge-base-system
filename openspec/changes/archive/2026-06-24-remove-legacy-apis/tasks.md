## 1. 工具函数迁移

- [x] 1.1 新建 `app/api/upload_utils.py`，从 `app/api/upload.py` 迁移 `_hash_upload()`、`save_upload_file()`、`DEFAULT_CATEGORY`、`CHUNK_SIZE`、`MINIO_PART_SIZE` 及其 import
- [x] 1.2 更新 `app/api/v1/documents.py`：`from app.api import upload as upload_api` → `from app.api import upload_utils as upload_api`
- [x] 1.3 确认 v1 上传接口行为不变

## 2. 删除旧版 API 文件

- [x] 2.1 删除 `app/api/upload.py`
- [x] 2.2 删除 `app/api/ingest.py`
- [x] 2.3 删除 `app/api/documents.py`
- [x] 2.4 删除 `app/api/search.py`

## 3. 路由注册清理

- [x] 3.1 `app/main.py`：移除 `legacy_upload`、`legacy_ingest`、`legacy_search`、`legacy_documents` 的 import 和 `include_router`

## 4. 测试清理

- [x] 4.1 `tests/test_document_dedup.py`：`from app.api import upload as upload_api` → `from app.api import upload_utils as upload_api`；删除 `from app.api import ingest as ingest_api`；改写 `POST /upload` 和 `POST /ingest` 测试为 v1 接口调用
- [x] 4.2 `tests/test_search_pipeline.py`：同上处理 import；改写 `POST /upload`、`POST /ingest`、`POST /search` 测试
- [x] 4.3 `tests/integration/test_documents_api.py`：删除 `POST /upload`、`POST /ingest`、`GET /ingest/{id}` 的向后兼容测试（约 L936-965）

## 5. 全量验证

- [x] 5.1 运行 `pytest tests/ -v` 确认无回归（基础测试 37/37 通过；PG 依赖的测试需 Docker 环境）
- [x] 5.2 确认 `POST /api/v1/documents/upload` 端到端流程正常（import 链验证通过）
