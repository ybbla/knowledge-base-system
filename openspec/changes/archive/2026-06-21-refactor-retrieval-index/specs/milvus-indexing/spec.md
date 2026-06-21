# Milvus Indexing (delta)

> 父 spec: `openspec/specs/milvus-indexing/spec.md`

## MODIFIED Requirements

### Requirement: Milvus Collection 自动创建与管理

系统 SHALL 在首次启动时自动创建 Milvus Collection，schema 包含 `chunk_id`（VarChar 主键）、`content`（VarChar，启用 `chinese` 分析器）、`dense_vector`（FloatVector 1024d）、`sparse_vector`（SparseFloatVector，由 BM25 Function 自动生成）、`category`（VarChar）、`knowledge_type`（VarChar）、`status`（VarChar，默认 `"active"`）、`title`（VarChar）、`asset_refs`（VarChar JSON）、`source_refs`（VarChar JSON）、`metadata`（VarChar JSON）、`doc_id`（VarChar）、`created_at`（Int64）、`updated_at`（Int64）等字段。Collection schema 定义 BM25 Function：`Function(name="bm25", function_type=FunctionType.BM25, input_field_names=["content"], output_field_names="sparse_vector")`。Collection schema SHALL NOT 包含 `index_status` 字段。

#### Scenario: 首次启动自动建 Collection
- **WHEN** Milvus 连接可用且目标 Collection 不存在
- **THEN** 系统按预定义 schema 创建 Collection，为 `dense_vector` 创建 HNSW 索引（M、efConstruction 可配置），为 `sparse_vector` 创建 SPARSE_INVERTED_INDEX（metric_type=BM25）
- **AND** `content` 字段启用 `enable_analyzer=True` 和 `analyzer_params={"type": "chinese"}`

#### Scenario: Collection 已存在且 schema 包含 BM25 Function 时跳过创建
- **WHEN** Milvus 连接可用且目标 Collection 已存在且 schema 的 functions 中包含 `FunctionType.BM25`
- **THEN** 系统加载已有 Collection 到内存，不修改 schema

#### Scenario: Collection 已存在但 schema 不含 BM25 Function 时自动迁移
- **WHEN** Milvus 连接可用且目标 Collection 已存在但 schema 不含 `FunctionType.BM25`
- **THEN** 系统检测到旧 schema，自动 drop 并重新创建 Collection（使用新 schema），随后从 PostgreSQL 全量重建索引

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
- **THEN** 返回按余弦相似度排序的前 top_k 个 chunk 的完整 entity 数据（`output_fields=["chunk_id", "content", "title", "category", "knowledge_type", "asset_refs", "source_refs", "metadata", "doc_id", "created_at", "updated_at"]`）及分数

#### Scenario: 按 category 和 knowledge_type 过滤 dense 检索
- **WHEN** 提交查询时附带 `category` 和 `knowledge_type` 过滤条件
- **THEN** Milvus 查询中携带 `(category == "value") && (knowledge_type == "value")` 的 filter expression

### Requirement: Sparse 向量索引（BM25）存储与检索

系统 SHALL 使用 Milvus 原生 BM25 Function 自动从 `content` 字段生成稀疏向量，存入 `sparse_vector` 字段，使用 `SPARSE_INVERTED_INDEX` + `BM25` 度量类型。检索时直接传入原始查询文本，Milvus 自动分词并计算 BM25 分数。

#### Scenario: 添加 BM25 数据到 Milvus
- **WHEN** chunk 写入 Milvus 时包含 `content` 字段
- **THEN** BM25 Function 自动对 `content` 执行 `chinese` 分析器分词，计算 BM25 统计并生成稀疏向量
- **AND** 无需在应用层调用 jieba 分词或计算 TF-IDF

#### Scenario: BM25 关键词检索
- **WHEN** 以 `top_k` 对查询文本提交到 `MilvusBM25Index.search()`
- **THEN** 查询参数为原始文本字符串，搜索使用 `metric_type="BM25"`
- **AND** 返回按 BM25 分数降序排列的 top_k 个 chunk 的完整 entity 数据及分数

### Requirement: Milvus Hybrid Search 双路融合

> **注意**：此 requirement 已被 `hybrid-retrieval` 中的变更完全替代。Milvus 不再负责双路融合，融合改为应用层 RRF。

### Requirement: Milvus 索引 CRUD 操作

系统 SHALL 支持向 Milvus 索引添加和删除知识块索引实体。

#### Scenario: 删除知识块索引
- **WHEN** 一个 chunk 被标记为 `deleted`
- **THEN** 其在 Milvus Collection 中的对应 entity 被删除

#### Scenario: 更新知识块元数据
- **WHEN** 知识块的 category、status 或其他标量字段发生变更
- **THEN** 系统 upsert Milvus entity，更新对应字段

### Requirement: Milvus 索引实现适配抽象接口

系统 SHALL 实现 `MilvusVectorIndex(VectorIndex)` 和 `MilvusBM25Index(BM25Index)` 类，匹配已有接口契约，使 `RetrievalPipeline` 和 `IngestionPipeline` 无需了解具体索引后端。

#### Scenario: MilvusVectorIndex 满足 VectorIndex 接口
- **WHEN** 实例化 `MilvusVectorIndex`
- **THEN** 其 `add()`、`delete()`、`search()` 方法签名与 `VectorIndex` ABC 完全一致

#### Scenario: MilvusBM25Index 满足 BM25Index 接口
- **WHEN** 实例化 `MilvusBM25Index`
- **THEN** 其 `add()`、`delete()`、`search()` 方法签名与 `BM25Index` ABC 完全一致

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

### Requirement: 检索结果直接从 Milvus 获取完整数据

系统 SHALL 在 search 时通过 `output_fields` 获取全部 chunk 字段，检索 pipeline 不再需要通过 PostgreSQL `chunk_store` 获取 chunk 详情。

#### Scenario: search 返回完整 chunk 数据
- **WHEN** 执行向量或 BM25 检索
- **THEN** `output_fields` 包含 `chunk_id`、`content`、`title`、`category`、`knowledge_type`、`asset_refs`、`source_refs`、`metadata`、`doc_id`、`created_at`、`updated_at`
- **AND** 检索 pipeline 可直接从返回的 entity 构建 `SearchResultItem`，无需额外查询

### Requirement: Milvus Collection 重建后自动恢复索引

当 Milvus Collection 因 Schema 变更需要重建时，系统 SHALL 在启动时通过 `rebuild_retrieval_indexes_from_chunks` 从 PostgreSQL 中的 `status='active'` 知识块全量重建索引。

#### Scenario: 启动时恢复索引
- **WHEN** 应用启动且 Milvus Collection 为空或不存在
- **THEN** `startup_resources()` 从 PostgreSQL 读取所有 `status='active'` 的 knowledge chunks 并重新写入 Milvus

## REMOVED Requirements

### Requirement: Milvus Hybrid Search 双路融合

**Reason**: 融合逻辑移至应用层 `rrf_fusion()`，Milvus 不再承担双路融合职责。两路并行 search 后在 Python 侧融合，逻辑更可控且消除 Hybrid Search 的 fallback 分支。

**Migration**: `indexing/milvus_hybrid.py` 删除，`retrieval/pipeline.py` 改为并行两路 + `rrf_fusion()`。

### Requirement: 全局 IDF 持久化

**Reason**: BM25 统计由 Milvus 内置 Tantivy 引擎管理，不再需要应用层 IDF 统计及 PostgreSQL `idf_stats` 表。

**Migration**: 删除 `DbIdfStat` ORM 模型和相关表。删除 `milvus_sparse_max_vocab` 配置项。
