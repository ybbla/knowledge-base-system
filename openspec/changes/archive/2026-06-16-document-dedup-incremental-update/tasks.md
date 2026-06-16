## 1. 基础设施：错误类型与数据库迁移

- [x] 1.1 在 `app/core/errors.py` 新增 `DuplicateDocumentError`、`VersionConflictError`、`DocumentNotFoundError` 异常类，均继承 `KnowledgeBaseError`
- [x] 1.2 创建数据库迁移脚本：`documents` 表新增部分唯一索引 `idx_documents_source_hash_active`（`WHERE status = 'active'`），`source_uri` 新增普通索引 `idx_documents_source_uri`

## 2. DocumentRepository 改造

- [x] 2.1 `DocumentRepository` 新增 `find_by_hash(source_hash: str) -> Document | None` 方法，按 hash 查找活跃文档
- [x] 2.2 `DocumentRepository` 新增 `find_by_source_uri(source_uri: str) -> Document | None` 方法
- [x] 2.3 `DocumentRepository.create()` 改为先 `SELECT` 检查 `doc_id` 是否存在，存在则抛出 `DuplicateDocumentError`，不存在才执行 `INSERT`（不再使用 `session.merge()`）
- [x] 2.4 `DocumentRepository.update()` 加入乐观锁：`UPDATE ... WHERE doc_id = :id AND version = :expected`，影响行数为 0 时抛出 `VersionConflictError`；成功后递增 `version`

## 3. 上传阶段去重

- [x] 3.1 `POST /upload` 中在写入 MinIO 之前，通过 `DocumentRepository.find_by_hash()` 查询是否已存在，命中则返回 `{"duplicate": true, "existing_doc_id": "..."}` 不写 MinIO
- [x] 3.2 确保 `status='failed'` 或 `status='deleted'` 的文档不拦截上传

## 4. 入库 API 改造

- [x] 4.0 `IngestDocument` Pydantic 模型新增必填字段 `source_hash: str`，由客户端从 `/upload` 响应中原样传入
- [x] 4.1 `IngestDocument` Pydantic 模型新增可选字段 `doc_id: str | None = None`
- [x] 4.2 `POST /ingest` 中对于 `doc_id` 为空的文档，按 `source_hash` 执行去重检查，命中活跃文档则在 `warnings` 中返回跳过信息
- [x] 4.3 对于 `doc_id` 有值的文档，查 DB 确认存在后进入更新分支；不存在返回 404；`source_hash` 未变化则返回 `"no_change": true`
- [x] 4.4 更新后的响应 `warnings` 字段包含被跳过文档的详情（`doc_id`、`reason`、`existing_doc_id`）

## 5. Milvus Schema 变更与 status 过滤

- [x] 5.0 实现 Collection Schema 迁移：`ensure_collection()` 检测已有 Collection 是否缺少 `status` 字段，若缺失则删除旧 Collection 并重建（开发阶段策略，满足 Milvus 不支持 ALTER TABLE 的约束）
- [x] 5.1 `MilvusCollectionManager.ensure_collection()` 的 Schema 新增 `status` 字段（VARCHAR，max_length=32，默认 `"active"`）
- [x] 5.2 `MilvusVectorIndex._build_fields()` 写入 `status` 为 `metadata.get("status", "active")`
- [x] 5.3 `MilvusSparseIndex.add_batch()` 的 fields_items 写入 `status` 字段
- [x] 5.4 `MilvusVectorIndex.search()` 的 expr 叠加 `status == "active"` 过滤条件
- [x] 5.5 `MilvusSparseIndex.search()` 的 expr 叠加 `status == "active"` 过滤条件
- [x] 5.6 `hybrid_search()` 中所有 `AnnSearchRequest` 的 expr 叠加 `status == "active"` 过滤
- [x] 5.7 `IngestionPipeline._chunk_index_metadata()` 新增 `"status": chunk.status.value` 写入索引元数据
- [x] 5.8 添加 `MilvusCollectionManager.update_status_batch(chunk_ids: list[str], status: str)` 方法，对一批 chunk_id 批量 upsert `status` 字段（需保留原有向量和元数据）
- [x] 5.9 `MilvusVectorIndex` 和 `MilvusSparseIndex` 暴露 `update_status_batch()` 代理方法

## 6. Chunk Store 改造

- [x] 6.1 `PgChunkStore` 新增 `bulk_update_status_by_doc_id(doc_id: str, status: str)` 方法，将指定文档下所有 `status='active'` 的 chunk 批量更新为新状态
- [x] 6.2 `PgChunkStore` 新增 `list_by_doc_id(doc_id: str) -> list[KnowledgeChunk]` 方法，按文档 ID 查找所有知识块（用于后续 Milvus 状态同步）

## 7. 索引基类扩展

- [x] 7.1 `VectorIndex` 抽象基类可选新增 `update_status_batch(chunk_ids: list[str], status: str)` 方法（默认空实现）
- [x] 7.2 `BM25Index` 抽象基类可选新增 `update_status_batch(chunk_ids: list[str], status: str)` 方法（默认空实现）
- [x] 7.3 内存索引 `MemoryVectorIndex` 和 `MemoryBM25Index` 实现 status 过滤支持

## 8. 入库管道增量更新

- [x] 8.1 `IngestionPipeline._run()` 新增更新分支：识别 `doc_id` 已存在 → 执行乐观锁 version 检查 → `version += 1`
- [x] 8.2 新增 `_update_existing_doc()` 私有方法：级联查找 `root_doc_id` 匹配的子文档，按深度排序后逐个重新解析
- [x] 8.3 新 chunks 写入索引成功后，调用 `PgChunkStore.bulk_update_status_by_doc_id()` 将旧 chunk 标记 `superseded`
- [x] 8.4 调用 `Milvus.update_status_batch()` 同步更新 Milvus 中旧 chunk 的 `status` 字段
- [x] 8.5 `_index_chunks()` 中先完成索引写入再标记旧 chunk（先写后淘汰，确保窗口期可检索）
- [x] 8.6 级联更新时，每个被更新的文档（含子文档）均需处理旧 chunk 标记和索引状态更新

## 9. 启动恢复

- [x] 9.1 `startup_resources()` 或 `rebuild_retrieval_indexes_from_chunks()` 在 Milvus Collection 重建后，只恢复 `status='active'` 的 knowledge chunks
- [x] 9.2 `recover_pending_chunk_indexes()` 同步适配 status 过滤

## 10. 测试

- [x] 10.1 新增 `tests/test_document_dedup.py`：验证上传去重（`duplicate` / 新文件 / `failed` 文档可重新上传）、入库去重（活跃文档拒绝 / 失败文档允许 / 更新路径绕过去重）
- [x] 10.2 新增 `tests/test_document_update.py`：验证增量更新（version 递增、旧 chunk 标记 superseded、`no_change` 检测、不存在的 doc_id 返回 404、级联更新子文档）
- [x] 10.3 新增 `tests/test_optimistic_lock.py`：验证乐观锁冲突抛出 `VersionConflictError`
- [x] 10.4 新增 `tests/test_milvus_status_filter.py`：验证写入 status 字段、检索 expr 过滤 `active`、`update_status_batch`
- [x] 10.5 更新 `tests/e2e/e2e_real_chain_file.py`：确保上传→入库→更新→检索 完整链路正常
