## Context

当前系统实现中，`Document` 的 `source_hash` 和 `version` 字段已在数据模型中定义但在业务逻辑中未实际使用。入库链路（upload → ingest → pipeline._run）采用"每次新建"模式，导致：

- 同一文件重复上传产生多条记录和多份索引向量
- 文档内容变更后只能新建文档，新旧数据失去关联
- `DocumentRepository.create()` 使用 `session.merge()` 静默 upsert，回避而非解决冲突

目标是在不改动核心解析和 LLM 抽取流程的前提下，补齐去重和增量更新两个能力。

## Goals / Non-Goals

**Goals:**
- 基于 `source_hash` 在入库全链路实现文档内容去重
- 支持通过显式 `doc_id` 对已有文档进行增量更新
- 旧知识块通过状态标记（`superseded`）而非物理删除来淘汰
- Milvus 索引检索自动过滤非 `active` 知识块
- 文档更新操作具备乐观锁保护

**Non-Goals:**
- 不实现自动更新检测（不通过 `source_uri` 自动匹配文档）
- 不实现知识块级的语义去重（L2 SimHash / L3 向量相似度）
- 不改变内存存储（MemoryAssetStore / ChunkStore）的行为，但内存索引（MemoryVectorIndex / MemoryBM25Index）需适配 status 过滤以保持接口一致
- 不修改解析器和 LLM 抽取器逻辑
- 不实现定时物理清理 `superseded` 知识块的后台任务（预留后续）

## Decisions

### 决策 1：以 `source_hash` 为内容唯一性判定依据

- **选型**：`source_hash`（SHA256）作为去重判断，`source_uri` 仅用于追溯和重新下载
- **理由**：`source_uri` 每次上传包含不同 `doc_id`，无法作为稳定标识；`source_hash` 是内容指纹，同一文件不论如何上传 hash 不变
- **备选**：按 `title + category` 去重 → 语义模糊，不可靠

### 决策 2：上传层 + 入库层双层去重

- **上传层（upload.py）**：计算 hash 后查 PostgreSQL，命中则返回 `{"duplicate": true, "existing_doc_id": "..."}` 不写 MinIO。属于软拦截，客户端自行决定后续操作
- **入库层（ingest.py）**：入库前按 hash 查重，`status='active'` 拒绝重复入库返回 warning；`failed`/`deleted` 允许重新入库（服务端硬拦截）
- **理由**：上传层节省 MinIO 存储和带宽，入库层提供最后防线

### 决策 3：显式 `doc_id` 触发更新

- **选型**：`/ingest` 的 `IngestDocument` 新增可选字段 `doc_id`，有值 → 更新，无值 → 新建
- **理由**：不依赖 `source_uri` 自动匹配，避免系统猜测用户意图。用户需明确表达"更新这个文档"
- **备选**：自动匹配 `source_uri` → 不可靠（`source_uri` 每次上传变化）；自动匹配 `source_hash` → 会混淆"新建相同内容文档"和"更新文档"

### 决策 4：先写新后标记旧（双标记）

- **选型**：更新时新 chunks 先写入索引（`status="active"`），确认成功后旧 chunks 在 PostgreSQL 和 Milvus 两层标记 `superseded`
- **理由**：窗口期新旧共存，检索不"消失"。Milvus 层过滤 `status == "active"` 避免回查 PostgreSQL
- **备选**：仅 PostgreSQL 标记 → 每次检索需回查过滤，top-k 可能被旧块占满

### 决策 5：Milvus Collection 新增 `status` 字段

- **选型**：在 Milvus schema 中新增 `status` VARCHAR 字段（默认 `"active"`），检索 expr 叠加 `status == "active"` 过滤，更新旧块时 upsert 实体只改 `status` 值
- **理由**：开发阶段 Schema 变更成本可接受；检索时零额外延迟
- **影响**：Milvus 不支持 ALTER TABLE，需重建 Collection，已有数据需重新索引（可通过 `startup_resources` → `rebuild_retrieval_indexes_from_chunks` 恢复）

### 决策 6：嵌入子文档级联更新

- **选型**：父文档更新时，级联处理所有 `root_doc_id = 父文档 doc_id` 的子文档
- **理由**：子文档的 `section_path` 等元数据可能随父文档结构变化而失效
- **备选**：仅更新父文档、子文档保留 → 元数据可能过时，且子文档的 LLM 抽取窗口划分依赖父文档上下文

### 决策 7：乐观锁防止并发更新

- **选型**：`DocumentRepository.update()` 用 `UPDATE ... WHERE doc_id = :id AND version = :expected, SET version = :expected + 1`，行数为 0 则抛出 `VersionConflictError`
- **理由**：比悲观锁（`SELECT FOR UPDATE`）更轻量，适合读写分离场景

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| Milvus Schema 变更导致已有索引数据丢失 | 通过 `rebuild_retrieval_indexes_from_chunks` 从 PostgreSQL 全量重建，开发阶段可接受 |
| `superseded` chunk 持续累积占用 Milvus 存储 | 暂不实现自动清理，但预留 `indexing_at` / `status` 字段便于后续定时任务按时间窗口清理 |
| 部分唯一索引 `WHERE status='active'` 依赖 PostgreSQL 特性 | 已知且可接受；MySQL 不支持部分索引，但项目仅使用 PostgreSQL |
| 上传层查重增加一次 DB 查询延迟 | 查询条件为 `source_hash` + `status`，可建索引优化至毫秒级 |
| 级联更新子文档可能放大单次更新成本 | 子文档数量受 `max_recursion_depth`（默认 3）限制，可控 |

## Migration Plan

1. **数据库迁移**（手动 SQL 或 Alembic）：
   ```sql
   CREATE UNIQUE INDEX idx_documents_source_hash_active
       ON documents (source_hash) WHERE status = 'active';
   CREATE INDEX idx_documents_source_uri ON documents (source_uri);
   ```
   回滚：`DROP INDEX idx_documents_source_hash_active; DROP INDEX idx_documents_source_uri;`

2. **Milvus Schema 变更**：重建 Collection（开发阶段可接受），启动时自动恢复索引

3. **应用层变更**：渐进式——先上 upload 去重（独立），再上 ingest 去重（与 upload 联动），最后上增量更新（依赖前两者）

## Open Questions

- `superseded` chunk 的自动清理策略：保留 N 天后清理？按版本数（只保留最新 3 版）？
- 是否需要 `/ingest` 的 `options` 中新增 `force` 参数强制跳过去重？