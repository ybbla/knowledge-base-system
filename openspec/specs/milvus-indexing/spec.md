# Milvus Indexing

## Purpose

将向量索引和 BM25 索引从进程内存迁移至 Milvus 后端，实现索引数据持久化。Milvus Collection 存储 dense vector（火山 Embedding 1024d，HNSW + COSINE）和 sparse vector（Milvus 原生 BM25 Function 自动生成，SPARSE_INVERTED_INDEX + BM25 度量）。两路搜索在应用层并行执行后通过 RRF 融合。Collection 包含 `status` 字段用于知识块生命周期管理，检索自动过滤非 `active` 块。PG CRUD 操作通过 `services.py` 统一同步到 Milvus。

> 新建自 change `phase-3-milvus-minio`，日期 2026-06-12；更新自 change `document-dedup-incremental-update`，日期 2026-06-15；更新自 change `simplify-status-model`，日期 2026-06-19；更新自 change `refactor-retrieval-index`，日期 2026-06-21。

## Requirements

### Requirement: Milvus Collection 自动创建与管理

系统 SHALL 在首次启动时自动创建 Milvus Collection，schema 包含 `chunk_id`（VarChar 主键）、`content`（VarChar，启用 `chinese` 分析器）、`dense_vector`（FloatVector 1024d）、`sparse_vector`（SparseFloatVector，由 BM25 Function 自动生成）、`category`（VarChar）、`knowledge_type`（VarChar）、`status`（VarChar，默认 `"active"`）、`title`（VarChar）、`asset_refs`（VarChar JSON）、`source_refs`（VarChar JSON）、`metadata`（VarChar JSON）、`doc_id`（VarChar）、`created_at`（Int64）、`updated_at`（Int64）等字段。Collection schema 定义 BM25 Function：`Function(name="bm25", function_type=FunctionType.BM25, input_field_names=["content"], output_field_names="sparse_vector")`。Collection schema SHALL NOT 包含 `index_status` 和 `title_path` 字段。

#### Scenario: 首次启动自动建 Collection
- **WHEN** Milvus 连接可用且目标 Collection 不存在
- **THEN** 系统按预定义 schema 创建 Collection，为 `dense_vector` 创建 HNSW 索引（M、efConstruction 可配置），为 `sparse_vector` 创建 SPARSE_INVERTED_INDEX（metric_type=BM25）
- **AND** `content` 字段启用 `enable_analyzer=True` 和 `analyzer_params={"type": "chinese"}`

#### Scenario: Collection 已存在且 schema 包含 BM25 索引时跳过创建
- **WHEN** Milvus 连接可用且目标 Collection 已存在且 sparse_vector 索引度量类型为 BM25
- **THEN** 系统加载已有 Collection 到内存，不修改 schema

#### Scenario: Collection 已存在但 schema 不含 BM25 索引时自动迁移
- **WHEN** Milvus 连接可用且目标 Collection 已存在但 sparse_vector 索引非 BM25
- **THEN** 系统检测到旧 schema，自动 drop 并重新创建 Collection（使用新 schema），随后可从 PostgreSQL 全量重建索引

#### Scenario: Milvus 不可用时回退
- **WHEN** `MILVUS_ENABLED=true` 但 Milvus 连接失败
- **THEN** 系统记录 ERROR 日志，检索不可用

### Requirement: Dense 向量索引存储与检索

系统 SHALL 将火山 Embedding 模型生成的 1024 维浮点向量存入 Milvus `dense_vector` 字段，使用 HNSW 索引 + COSINE 距离度量，支持按相似度检索和按 `category`、`knowledge_type`、`status` 过滤。

#### Scenario: 添加 dense 向量到 Milvus
- **WHEN** 为知识块生成嵌入向量后
- **THEN** 向量连同 chunk 标量字段（`chunk_id`、`content`、`title`、`category`、`knowledge_type`、`status`、`asset_refs`、`source_refs`、`metadata`、`doc_id`、`created_at`、`updated_at`）写入 Milvus

#### Scenario: Dense 向量相似度检索
- **WHEN** 以 `top_k` 提交查询嵌入到 `MilvusVectorIndex.search()`
- **THEN** 返回按余弦相似度排序的前 top_k 个 chunk 的 chunk_id 及分数

#### Scenario: 按 category 和 knowledge_type 过滤 dense 检索
- **WHEN** 提交查询时附带 `category` 和 `knowledge_type` 过滤条件
- **THEN** Milvus 查询中携带对应的 filter expression

### Requirement: Sparse 向量索引（BM25）存储与检索

系统 SHALL 使用 Milvus 原生 BM25 Function 自动从 `content` 字段生成稀疏向量，存入 `sparse_vector` 字段，使用 `SPARSE_INVERTED_INDEX` + `BM25` 度量类型。检索时直接传入原始查询文本，Milvus 自动分词并计算 BM25 分数。

#### Scenario: 添加 BM25 数据到 Milvus
- **WHEN** chunk 写入 Milvus 时包含 `content` 字段
- **THEN** BM25 Function 自动对 `content` 执行 `chinese` 分析器分词，计算 BM25 统计并生成稀疏向量
- **AND** 无需在应用层调用 jieba 分词或计算 TF-IDF

#### Scenario: BM25 关键词检索
- **WHEN** 以 `top_k` 对查询文本提交到 `MilvusBM25Index.search()`
- **THEN** 查询参数为原始文本字符串，搜索使用 `metric_type="BM25"`
- **AND** 返回按 BM25 分数降序排列的 top_k 个 chunk_id 及分数

### Requirement: Milvus 索引 CRUD 操作

系统 SHALL 支持向 Milvus 索引添加、删除和更新知识块索引实体。

#### Scenario: 删除知识块索引
- **WHEN** 一个 chunk 被标记为 `deleted`
- **THEN** 其在 Milvus Collection 中的 entity 状态同步为 `deleted`

#### Scenario: 更新知识块元数据
- **WHEN** 知识块的 category、status 或其他标量字段发生变更
- **THEN** 系统通过 `services.py` 统一入口 upsert Milvus entity，更新对应字段

### Requirement: Milvus 索引实现适配抽象接口

系统 SHALL 实现 `MilvusVectorIndex(VectorIndex)` 和 `MilvusBM25Index(BM25Index)` 类，匹配已有接口契约，使 `RetrievalPipeline` 和 `IngestionPipeline` 无需了解具体索引后端。

#### Scenario: MilvusVectorIndex 满足 VectorIndex 接口
- **WHEN** 实例化 `MilvusVectorIndex`
- **THEN** 其 `add()`、`delete()`、`search()`、`upsert_fields()` 方法签名与 `VectorIndex` ABC 完全一致

#### Scenario: MilvusBM25Index 满足 BM25Index 接口
- **WHEN** 实例化 `MilvusBM25Index`
- **THEN** 其 `add()`、`delete()`、`search()`、`upsert_fields()` 方法签名与 `BM25Index` ABC 完全一致

### Requirement: 检索时自动过滤非 active 知识块

所有 Milvus 检索操作（dense vector search、sparse vector search）SHALL 在搜索表达式（expr）中叠加 `status == "active"` 过滤条件，确保不返回已淘汰的知识块。当指定 `category` 和 `knowledge_type` 时，叠加对应过滤条件。

#### Scenario: 向量检索只返回 active 知识块
- **WHEN** 执行 `VectorIndex.search()` 查询
- **THEN** Milvus search expr 包含 `status == "active"` 条件

#### Scenario: BM25 检索只返回 active 知识块
- **WHEN** 执行 `MilvusBM25Index.search()` 查询
- **THEN** Milvus search expr 包含 `status == "active"` 条件

#### Scenario: 按 category 和 knowledge_type 过滤时叠加 status 条件
- **WHEN** 检索请求指定 `category = "产品使用"` 和 `knowledge_type = "declarative"`
- **THEN** Milvus expr 为 `(category == "产品使用") && (knowledge_type == "declarative") && (status == "active")`

### Requirement: PG CRUD 自动同步 Milvus 索引

系统 SHALL 在所有 PG chunk CRUD 操作后自动同步 Milvus 索引——通过 `services.py` 的 `sync_index_metadata()` / `sync_index_metadata_batch()` 作为统一入口，确保 delete、restore、update 和 batch 操作后 Milvus 索引状态与 PG 一致。

#### Scenario: 软删除同步
- **WHEN** chunk 被软删除（`status="deleted"`）
- **THEN** Milvus 中该 entity 的 status 同步为 `deleted`

#### Scenario: 恢复同步
- **WHEN** chunk 被恢复（`status="active"`）
- **THEN** Milvus 中该 entity 的 status 同步为 `active`

#### Scenario: 元数据更新同步
- **WHEN** chunk 的 category 或 knowledge_type 发生变更
- **THEN** Milvus 中对应字段同步更新

### Requirement: Milvus Collection 重建后自动恢复索引

当 Milvus Collection 因 Schema 变更需要重建时，系统 SHALL 通过 `rebuild_retrieval_indexes_from_chunks` 从 PostgreSQL 中的 `status='active'` 知识块全量批量重建索引。

#### Scenario: 手动触发恢复索引
- **WHEN** 调用 `rebuild_retrieval_indexes_from_chunks()`
- **THEN** 从 PostgreSQL 读取所有 `status='active'` 的 knowledge chunks 并批量写入 Milvus

## REMOVED Requirements

### Requirement: Milvus Hybrid Search 双路融合

**Reason**: 融合职责移至应用层 `rrf_fusion()`（见 `hybrid-retrieval`）。**Migration**: 删除 `indexing/milvus_hybrid.py`。

### Requirement: 全局 IDF 持久化

**Reason**: BM25 统计由 Milvus 内置 Tantivy 引擎管理。**Migration**: 删除 `DbIdfStat` ORM 模型和 `idf_stats` 表，删除 `milvus_sparse_max_vocab` 配置。
