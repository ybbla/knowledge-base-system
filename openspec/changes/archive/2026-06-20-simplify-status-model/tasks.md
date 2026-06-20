## 1. 状态枚举与 Pydantic 模型

- [x] 1.1 修改 `app/core/models.py` — DocStatus 移除 `pending`（已无此值，仅更新注释说明流转规则）
- [x] 1.2 修改 `app/core/models.py` — ChunkStatus 枚举已为 `active`/`deleted`，仅清理代码中裸字符串 `"superseded"`
- [x] 1.3 修改 `app/core/models.py` — AssetStatus 简化为 `ready`/`failed`，移除 `pending`/`skipped`
- [x] 1.4 删除 `app/core/models.py` — ChunkIndexStatus 枚举（含 4 个值：pending/indexing/indexed/failed）
- [x] 1.5 修改 `app/core/models.py` — Document Pydantic 已移除 `ingest_job_id`，已有 `previous_doc_id`/`error_message`
- [x] 1.6 修改 `app/core/models.py` — KnowledgeChunk Pydantic 移除 `doc_version`/`index_status`/`indexed_at`/`index_error`/`ingest_job_id`
- [x] 1.7 修改 `app/core/models.py` — Asset Pydantic 默认 status 从 `AssetStatus.pending` 改为 `AssetStatus.ready`
- [x] 1.8 修改 `app/core/errors.py` — 移除 `VersionConflictError`（保留 `DuplicateDocumentError`）

## 2. 数据库模型

- [x] 2.1 修改 `app/db/models.py` — DbDocument 的 `ingest_job_id` 列已有废弃注释，确认代码层无读写
- [x] 2.2 修改 `app/db/models.py` — DbKnowledgeChunk 的 `doc_version`/`index_status`/`indexed_at`/`index_error`/`ingest_job_id` 列加 deprecated 注释

## 3. Repository 层

- [x] 3.1 修改 `app/db/repositories/documents.py` — `_to_db`/`_from_db` 已无 `ingest_job_id`
- [x] 3.2 修改 `app/db/repositories/documents.py` — `list_paginated` 已无 `ingest_job_id` 参数
- [x] 3.3 修改 `app/db/repositories/documents.py` — `find_similar_by_filename()` 已实现
- [x] 3.4 修改 `app/db/repositories/documents.py` — `get_version_history()` 已实现
- [x] 3.5 修改 `app/db/repositories/chunks.py` — `_to_db`/`_from_db` 去除 `doc_version`/`index_status`/`indexed_at`/`index_error`/`ingest_job_id`
- [x] 3.6 修改 `app/db/repositories/chunks.py` — `list_paginated` 去掉 `index_status`/`doc_version`/`ingest_job_id` 筛选参数
- [x] 3.7 删除 `app/db/repositories/chunks.py` — `list_by_index_status()` 方法
- [x] 3.8 删除 `app/db/repositories/chunks.py` — `update_index_status()` 方法
- [x] 3.9 重构 `app/db/repositories/chunks.py` — `bulk_update_status_by_doc_id()` 方法，去除 superseded 标记逻辑，保留用于 deleted/active 批量状态更新

## 4. Ingestion Pipeline 简化

- [x] 4.1 修改 `ingestion/pipeline.py` — 移除 JobStatus 类（pending/processing/completed/failed/canceled），改为同步执行 + doc.status 反映结果
- [x] 4.2 修改 `ingestion/pipeline.py` — 移除 `mode=incremental` 分支（`_run_update`），统一为 `_run_create`
- [x] 4.3 修改 `ingestion/pipeline.py` — 移除 `"superseded"` 裸字符串，旧 chunk 标记改为 `"deleted"`
- [x] 4.4 修改 `ingestion/pipeline.py` — 移除 `_mark_index_status()` 方法和 ChunkIndexStatus 流转（pending→indexing→indexed→failed）
- [x] 4.5 修改 `ingestion/pipeline.py` — 索引失败直接 `doc.status = DocStatus.failed` + `doc.error_message = str(exc)`
- [x] 4.6 修改 `ingestion/pipeline.py` — 更新流程：软删除旧文档(chunk→deleted) → 创建新文档(version+1, previous_doc_id) → 入库
- [x] 4.7 修改 `app/core/deps.py` — 移除 `ChunkIndexStatus` import；删除 `recover_pending_chunk_indexes()` 或改为按 `status=active` 恢复
- [x] 4.8 修改 `ingestion/recursive_loader.py` — 确认 `doc.status` 赋值使用 `DocStatus.processing` 而非裸字符串

## 5. API 端点 — Document

- [x] 5.1 修改 `app/api/v1/documents.py` — `_doc_to_item` 已含 `previous_doc_id`/`error_message`，无 `ingest_job_id`
- [x] 5.1b 修改 `app/api/v1/documents.py` — `_build_index_summary` 不再按 `index_status` 查询，改为简单 chunk count
- [x] 5.2 修改 `app/api/v1/documents.py` — `list_documents` 已无 `ingest_job_id` 参数
- [x] 5.3 修改 `app/api/v1/documents.py` — `upload_document` 已有 `replace_doc_id`/`confirm_replace`/`suggested_replace` 逻辑
- [x] 5.4 修改 `app/api/v1/documents.py` — `upload_document` 去掉 `mode` 参数（当前默认 `incremental`），统一为创建模式
- [x] 5.5 删除 `app/api/v1/documents.py` — `PATCH /{doc_id}` 端点（line 512-597，含乐观锁逻辑）
- [x] 5.6 删除 `app/api/v1/documents.py` — `POST /{doc_id}/ingest` 端点（已删除）
- [x] 5.7 新增 `app/api/v1/documents.py` — `GET /{doc_id}/history` 版本历史端点（已实现）
- [x] 5.8 修改 `app/api/v1/documents.py` — `restore_document` 已不依赖 ChunkIndexStatus
- [x] 5.9 修改 `app/api/v1/documents.py` — `create_document` 返回的 `ingest_job_id` 随 JobStatus 移除后自然清理

## 6. API 端点 — Chunk

- [x] 6.1 修改 `app/api/v1/chunks.py` — `_chunk_to_list_item`/`_chunk_to_detail` 去掉 `index_status`/`indexed_at`/`index_error`/`doc_version`
- [x] 6.2 修改 `app/api/v1/chunks.py` — `list_chunks` 查询参数去掉 `index_status`
- [x] 6.3 修改 `app/api/v1/chunks.py` — `create_chunk`/`update_chunk` 移除 ChunkIndexStatus 赋值（indexing/indexed/failed/pending）
- [x] 6.4 删除 `app/api/v1/chunks.py` — `POST /batch/reindex` 端点（line 395）
- [x] 6.5 删除 `app/api/v1/chunks.py` — `POST /{chunk_id}/reindex` 端点（line 423）
- [x] 6.6 修改 `app/api/v1/chunks.py` — `restore_chunk` 去掉 ChunkIndexStatus 检查，恢复后直接触发索引
- [x] 6.7 修改 `app/api/v1/chunks.py` — 移除 `from app.core.models import ChunkIndexStatus`

## 7. API 端点 — Ingest（删除）

- [x] 7.1 删除 `app/api/v1/ingest.py` 整个文件（含 `job_to_dict` 辅助函数）
- [x] 7.2 修改 `app/api/v1/__init__.py` — 移除 `import ingest` + `router.include_router(ingest.router)`
- [x] 7.3 修改 `app/api/v1/documents.py` — 移除 `from app.api.v1.ingest import job_to_dict`

## 8. API 端点 — Search

- [x] 8.1 修改 `app/api/v1/search.py` — `SearchFilters.index_status` 字段移除
- [x] 8.2 修改 `app/api/v1/search.py` — `GET /filters` 响应去掉 `index_statuses` 统计
- [x] 8.3 修改 `app/api/v1/services.py` — 移除 `ChunkIndexStatus` import 和 `update_index_status()` 调用

## 9. 索引层

- [x] 9.1 修改 `indexing/milvus_vector.py` — 删除 `update_status_batch()` 方法（两处）
- [x] 9.2 修改 `indexing/milvus_sparse.py` — 删除 `update_status_batch()` 方法
- [x] 9.3 修改 `indexing/milvus_hybrid.py` — 确认搜索 expr 无 `index_status` 引用（当前仅用 `status=="active"`）
- [x] 9.4 修改 `indexing/memory_vector.py` — 删除 `update_status_batch()` 方法
- [x] 9.5 修改 `indexing/memory_bm25.py` — 删除 `update_status_batch()` 方法
- [x] 9.6 修改 `indexing/base.py` — `VectorIndex` 和 `BM25Index` ABC 中删除 `update_status_batch()` 抽象方法

## 10. 前端

- [x] 10.1 删除 `frontend/js/components/ingestion.js`
- [x] 10.2 修改 `frontend/index.html` — 去掉 `<script src="js/components/ingestion.js">` 和导航栏入库入口
- [x] 10.3 修改 `frontend/js/app.js` — 去掉 `/ingestion` 路由 + `Ingestion` 引用
- [x] 10.4 修改 `frontend/js/components/common.js` — `statusBadge()` 精简：去掉 `pending`/`accepted`/`completed`/`canceled`/`indexed`/`superseded`，保留 `active`/`deleted`/`failed`/`processing`/`ready`
- [x] 10.5 修改 `frontend/js/components/documents.js` — 状态筛选添加 `processing`/`deleted` 选项（当前仅 `active`/`failed`）
- [x] 10.6 修改 `frontend/js/components/documents.js` — 去掉 `ingest_job_id` 列（已无此列）
- [x] 10.7 修改 `frontend/js/components/documents.js` — 上传逻辑处理 `suggested_replace` 响应 + 确认更新弹窗
- [x] 10.8 修改 `frontend/js/components/chunks.js` — 去掉 `chunkIndexFilter` 下拉框；去掉表格 `index_status` 列
- [x] 10.9 修改 `frontend/js/components/chunks.js` — `chunkStatusLabel` 去掉 `superseded: '已替换'`；删除 `indexStatusLabel()` 函数
- [x] 10.10 修改 `frontend/js/components/document-detail.js` — chunk card 的 `index_status` badge 改为 `status` badge
- [x] 10.11 修改 `frontend/js/components/search.js` — 默认过滤去掉 `index_status: ['indexed']`（line 83/104）
- [x] 10.12 修改 `frontend/js/api.js` — 删除 `ingestDocument()`/`listIngestJobs()`/`getIngestJob()`/`retryIngestJob()`/`cancelIngestJob()` 函数

## 11. 测试更新

- [x] 11.1 更新 `tests/test_models.py` — ChunkStatus 期望值从 `{"active","superseded","deleted"}` → `{"active","deleted"}`；移除 ChunkIndexStatus/AssetStatus 测试
- [x] 11.2 更新 `tests/test_db_models.py` — 移除 `index_status`/`doc_version`/`ingest_job_id`/`superseded` 相关断言
- [x] 11.3 更新 `tests/test_db_repositories.py` — 适配 chunks repo 接口变更（list_by_index_status/update_index_status 删除）
- [x] 11.4 更新 `tests/integration/test_documents_api.py` — 删除 PATCH 乐观锁测试；删除 `/{doc_id}/ingest` 测试；状态值更新
- [x] 11.5 更新 `tests/integration/test_chunks_api.py` — 去掉 `index_status` 断言（`pending`/`indexed` 等）
- [x] 11.6 删除 `tests/integration/test_ingestion_jobs_api.py`
- [x] 11.7 删除 `tests/test_optimistic_lock.py`
- [x] 11.8 删除 `tests/test_document_update.py`
- [x] 11.9 更新 `tests/test_v1_documents_chunks.py` — 适配状态枚举变更
- [x] 11.10 更新 `tests/test_v1_search.py` — 去掉 `index_status`/`chunk_status=["active"]` 筛选参数
- [x] 11.11 更新 `tests/test_v1_ingest_upload.py` — 去掉 JobStatus 引用
- [x] 11.12 更新 `tests/test_milvus_status_filter.py` — 去掉 `superseded`/`index_status` 相关测试
- [x] 11.13 更新 `tests/test_batch_indexing.py` — 去掉 ChunkIndexStatus import
- [x] 11.14 更新 `tests/conftest.py` — 清理 ingest fixtures

## 12. 数据迁移与清理

- [x] 12.1 数据迁移脚本 — 存量 `status=superseded` 的 chunk 批量更新为 `deleted`
- [x] 12.2 最终检查 — Grep 全项目确认无 `ChunkIndexStatus`/`superseded`/`update_status_batch`/`index_status`/`job_to_dict` 残留引用
- [x] 12.3 运行全量测试 `pytest tests/ -v` 确认无回归
