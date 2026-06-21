## 1. 配置变更

- [x] 1.1 新增 `milvus_hnsw_M`（默认 16）、`milvus_hnsw_ef_construction`（默认 200）、`milvus_hnsw_ef`（默认 64）
- [x] 1.2 新增 `milvus_sparse_ef`（默认 16）
- [x] 1.3 删除 `milvus_sparse_max_vocab`

## 2. Schema 迁移 (`indexing/milvus_vector.py`)

- [x] 2.1 更新 `_default_entity()`：14 字段（删 `title_path`，增 `title` + `updated_at`）
- [x] 2.2 更新 `_build_fields()`：同步字段变更
- [x] 2.3 `ensure_collection()`：`content` 字段加 `enable_analyzer=True` + `analyzer_params={"type": "chinese"}`
- [x] 2.4 创建 BM25 Function + `CollectionSchema(fields, functions=[bm25_func])`
- [x] 2.5 BM25 Function 迁移检测：`collection.schema.functions` 不含 `FunctionType.BM25` 则 drop 重建
- [x] 2.6 Dense 索引改为 `HNSW` + `COSINE`
- [x] 2.7 `ensure_sparse_index()`：`metric_type` 从 `IP` 改为 `BM25`
- [x] 2.8 `MilvusVectorIndex.search()`：签名加 `knowledge_type`，param 从 `nprobe` 改为 `ef`，expr 拼接 knowledge_type

## 3. 入库元数据更新 (`ingestion/pipeline.py`)

- [x] 3.1 `_chunk_index_metadata()` 新增 `"title": chunk.title`
- [x] 3.2 新增 `"created_at"` 和 `"updated_at"` 时间戳
- [x] 3.3 删除 `"title_path"`（值已在 `"metadata"` JSON 中）

## 4. 新建 MilvusBM25Index (`indexing/milvus_bm25.py`)

- [x] 4.1 创建文件，实现 `BM25Index` 接口
- [x] 4.2 `add_batch()`：写入 content + 全部标量字段
- [x] 4.3 `search()`：签名含 `knowledge_type`，传原始文本，`anns_field="sparse_vector"`，`metric_type="BM25"`
- [x] 4.4 `delete()` + `upsert_fields()` + `upsert_fields_batch()`：委托 manager

## 4bis. 修复 CRUD -> Milvus 同步 (`services.py` + `chunks.py` + `documents.py`)

- [x] 4bis.1 `MilvusVectorIndex` 新增 `upsert_fields()` / `upsert_fields_batch()`
- [x] 4bis.2 `MilvusBM25Index` 同步新增 `upsert_fields()` / `upsert_fields_batch()`
- [x] 4bis.3 修 `services.py`：`_sync_vector_metadata()` / `_sync_bm25_metadata()` 改为调 `upsert_fields()`
- [x] 4bis.4 `chunks.py` delete/restore/update/batch 端点加 `sync_index_metadata()` 调用
- [x] 4bis.5 `documents.py` 统一用 `services.py` 封装，删除直接调 index 和 try-except-pass

## 5. Pipeline 重构 (`retrieval/pipeline.py`)

- [x] 5.1 移除 `from indexing.milvus_hybrid import hybrid_search`
- [x] 5.2 `search()` 签名新增 `knowledge_type` 参数，透传到两路 Milvus expr
- [x] 5.3 `ThreadPoolExecutor` 两路并行搜索
- [x] 5.4 删除 hybrid_results 分支和 fallback，统一走 `rrf_fusion()`
- [x] 5.5 删除 `RetrievalDebugInfo.used_milvus_hybrid`

## 6. search API 透传 (`app/api/v1/search.py`)

- [x] 6.1 调用 `pipeline.search()` 时传入 `knowledge_type`（从 `filters.knowledge_types[0]` 取）
- [x] 6.2 debug 检索入口同步传入

## 7. 依赖注入更新 (`app/core/deps.py`)

- [x] 7.1 `MilvusSparseIndex` -> `MilvusBM25Index`，共享 manager
- [x] 7.2 移除 `session_factory` 参数
- [x] 7.3 `rebuild_retrieval_indexes_from_chunks()` 改为批量 `add_batch()`

## 8. 删除旧代码

- [x] 8.1 删除 `indexing/milvus_hybrid.py`
- [x] 8.2 删除 `indexing/milvus_sparse.py`
- [x] 8.3 删除 `indexing/memory_bm25.py`
- [x] 8.4 删除 `app/db/models.py` 中 `DbIdfStat` 类
- [x] 8.5 删除 `app/api/v1/search.py` 中 `used_milvus_hybrid` 字段
- [x] 8.6 更新 `tests/evaluation/tune_params.py` 移除 `milvus_hybrid` 模式

## 9. 测试更新

- [x] 9.1 `tests/test_milvus_indexing.py`：`MilvusSparseIndex` -> `MilvusBM25Index`
- [x] 9.2 `tests/test_batch_indexing.py`：同上
- [x] 9.3 `tests/test_v1_real_endpoints.py`：`FakeDebugInfo` 删 `used_milvus_hybrid`
- [x] 9.4 `tests/test_db_models.py`：删 `TestDbIdfStat`

## 10. 数据迁移与验证

- [x] 10.1 启动服务，确认 `ensure_collection()` 自动检测并重建
- [x] 10.2 确认 BM25 Function 和 HNSW 索引创建成功
- [x] 10.3 `pytest tests/test_batch_indexing.py tests/test_milvus_indexing.py -v`
- [x] 10.4 `pytest tests/test_v1_real_endpoints.py -v`
- [x] 10.5 Playwright：后端启动 -> 搜索页 -> 搜索 -> 拍快照
