## Why

当前系统对文档入库无任何去重机制——同一文件上传两次会产生两条独立记录、两份索引向量，导致检索结果重复、存储浪费。同时系统只支持"新建"模式，无法对已有文档进行增量更新（内容变更后重新入库），每次修改只能走新建流程，新旧数据无法关联。设计文档（KNOWLEDGE_BASE_DEVELOPMENT.md）已明确定义 `source_hash` 用于识别重复文档和判断内容变化、`version` 字段用于增量更新时递增——这层语义在代码中尚未落地。

## What Changes

- **上传阶段去重**：计算 `source_hash` 后先查 PostgreSQL，已存在则直接返回已有文档信息，不再写入 MinIO
- **入库阶段去重**：入库前按 `source_hash` 查重，`status='active'` 的文档拒绝重复入库，`failed`/`deleted` 允许重新入库
- **数据库唯一约束**：`documents` 表新增 `source_hash` 部分唯一索引（`WHERE status = 'active'`），作为最后防线
- **增量更新**：`/ingest` 请求支持可选 `doc_id` 字段，指定则走更新流程——`version` 递增、旧知识块标记 `superseded`、重新解析和索引
- **Milvus Schema 变更**：新增 `status` 字段，检索时自动过滤 `status != 'active'` 的知识块，更新时通过 upsert 标记而非物理删除
- **乐观锁**：`DocumentRepository.update()` 新增 `WHERE version = :expected` 条件，防止并发更新覆盖
- **级联更新嵌入子文档**：父文档更新时，级联处理所有 `root_doc_id` 匹配的子文档
- **新增错误类型**：`DuplicateDocumentError`、`VersionConflictError`、`DocumentNotFoundError`

## Capabilities

### New Capabilities

- `document-deduplication`: 基于 `source_hash` 的文档内容去重，上传和入库两层拦截，数据库部分唯一索引兜底
- `document-incremental-update`: 基于 `doc_id` + `version` 的文档增量更新，旧知识块标记 `superseded` 并从检索过滤
- `milvus-status-filtering`: Milvus 索引新增 `status` 字段，检索 expr 自动过滤非 `active` 知识块
- `optimistic-locking`: 文档级别的乐观锁，`update` 时校验 `version` 防止并发覆盖

### Modified Capabilities

<!-- 无现有 specs，无修改 -->

## Impact

| 影响面 | 文件 | 说明 |
|--------|------|------|
| 数据模型 | `app/db/models.py` | `DbDocument.source_hash` 加部分唯一索引；Milvus schema 新增 `status` 字段 |
| 错误类型 | `app/core/errors.py` | 新增 DuplicateDocumentError、VersionConflictError、DocumentNotFoundError |
| 文档仓库 | `app/db/repositories/documents.py` | 新增 `find_by_hash()`、`find_by_source_uri()`；`create()` 改先查后 insert；`update()` 加乐观锁 |
| 上传 API | `app/api/upload.py` | 上传前按 `source_hash` 查重，命中返回 duplicate 不写 MinIO |
| 入库 API | `app/api/ingest.py` | `IngestDocument` 新增必填 `source_hash`、可选 `doc_id`；入库前按 hash 查重 |
| 入库管道 | `ingestion/pipeline.py` | 新增更新分支：乐观锁、级联子文档、旧 chunk 标记、索引状态管理 |
| 知识块仓库 | `app/db/repositories/chunks.py` | 新增 `bulk_update_status_by_doc_id()` |
| 索引抽象 | `indexing/base.py` | 可选：新增 `update_status_batch()` 抽象方法 |
| Milvus 索引 | `indexing/milvus_vector.py`、`indexing/milvus_sparse.py`、`indexing/milvus_hybrid.py` | Schema 新增 status；search expr 叠加过滤；upsert 支持状态更新 |
| 内存索引 | `indexing/memory_vector.py`、`indexing/memory_bm25.py` | status 过滤支持（保持接口一致） |

**回滚计划**：数据库迁移仅新增索引（可回退 `DROP INDEX`），Milvus Collection 在开发阶段可直接重建，应用层去重逻辑由配置项控制开关。
