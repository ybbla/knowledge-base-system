# Milvus Indexing

## Purpose

将向量索引和 BM25 索引从进程内存迁移至 Milvus，实现索引数据持久化。Milvus Collection 同时存储 dense vector（火山 Embedding 1024d）和 sparse vector（jieba + TF-IDF 编码），通过 Hybrid Search API 完成双路融合检索。

## ADDED Requirements

### Requirement: Milvus Collection 自动创建与管理

系统 SHALL 在首次启动时自动创建 Milvus Collection，schema 包含 `chunk_id`（VarChar 主键）、`doc_id`（VarChar）、`content`（VarChar）、`dense_vector`（FloatVector 1024d）、`sparse_vector`（SparseFloatVector）、`category`（VarChar）、`knowledge_type`（VarChar）、`title_path`（JSON）、`source_refs`（JSON）、`asset_refs`（JSON）、`metadata`（JSON）、`created_at`（Int64）等字段。

#### Scenario: 首次启动自动建 Collection

- **WHEN** Milvus 连接可用且目标 Collection 不存在
- **THEN** 系统按预定义 schema 创建 Collection，为 `dense_vector` 创建 IVF_FLAT 索引（nlist 可配置，默认 128），为 `sparse_vector` 创建 SPARSE_INVERTED_INDEX

#### Scenario: Collection 已存在时跳过创建

- **WHEN** Milvus 连接可用且目标 Collection 已存在
- **THEN** 系统加载已有 Collection 到内存，不修改 schema

#### Scenario: Milvus 不可用时回退

- **WHEN** `MILVUS_ENABLED=true` 但 Milvus 连接失败
- **THEN** 系统记录 ERROR 日志，回退到内存索引实现（MemoryVectorIndex / MemoryBM25Index）

### Requirement: Dense 向量索引存储与检索

系统 SHALL 将火山 Embedding 模型生成的 1024 维浮点向量存入 Milvus `dense_vector` 字段，支持按相似度检索和按 `category` 过滤。

#### Scenario: 添加 dense 向量到 Milvus

- **WHEN** 为知识块生成嵌入向量后
- **THEN** 向量和元数据（chunk_id、doc_id、content、category、knowledge_type、title_path、source_refs、asset_refs、metadata）同时写入 Milvus Collection

#### Scenario: Dense 向量相似度检索

- **WHEN** 以 `top_k=50` 提交查询嵌入到 `MilvusVectorIndex.search()`
- **THEN** 返回按 IP 距离（或余弦相似度）排序的前 50 个 chunk_id 及分数

#### Scenario: 按 category 过滤 dense 检索

- **WHEN** 提交查询时附带 `category` 过滤条件
- **THEN** Milvus 查询中携带 `category == "value"` 的 filter expression，仅返回匹配结果

### Requirement: Sparse 向量索引（BM25）存储与检索

系统 SHALL 使用 jieba 对 `content` 分词后生成 TF-IDF 稀疏向量，存入 Milvus `sparse_vector` 字段，支持关键词检索。

#### Scenario: 添加 BM25 稀疏向量到 Milvus

- **WHEN** 创建了一个 KnowledgeChunk
- **THEN** 系统用 jieba 对 `content` 分词，计算 TF-IDF 权重，生成 `{token_id: weight}` 稀疏向量写入 Milvus

#### Scenario: BM25 关键词检索

- **WHEN** 以 `top_k=50` 对查询文本分词后生成稀疏向量提交到 `MilvusSparseIndex.search()`
- **THEN** 返回按 IP 距离排序的前 50 个 chunk_id 及分数

#### Scenario: 全局 IDF 持久化

- **WHEN** 新知识块入库更新 IDF 值
- **THEN** 更新后的 IDF 字典持久化到 PostgreSQL `idf_stats` 表（或 Milvus 单独 collection），重启后无需重新计算

### Requirement: Milvus Hybrid Search 双路融合

系统 SHALL 使用 Milvus `hybrid_search()` API 同时查询 dense 和 sparse 向量，使用 `RRFRanker`（k=60）融合两路分数，返回单一排序结果。

#### Scenario: Hybrid Search 正常路径

- **WHEN** 检索请求进入且 Milvus 可用
- **THEN** 系统调用 `hybrid_search(dense_req + sparse_req, RRFRanker(k=60))` 获取融合后的 top_k 结果

#### Scenario: Hybrid Search 返回分数明细

- **WHEN** Hybrid Search 返回结果
- **THEN** 每个结果的 `score_components` 包含 `vector`（dense 分数）和 `bm25`（sparse 分数），`score` 为融合后分数

#### Scenario: Hybird Search 不可用时 fallback

- **WHEN** Milvus Hybrid Search 失败或不可用
- **THEN** 系统分别调用 `search(dense)` 和 `search(sparse)`，在应用层执行 RRF 融合

### Requirement: Milvus 索引 CRUD 操作

系统 SHALL 支持向 Milvus 索引添加、删除和按 `chunk_id` 查询知识块。

#### Scenario: 删除知识块索引

- **WHEN** 一个 chunk 被标记为 deleted 或 superseded
- **THEN** 其在 Milvus Collection 中的对应 entity 被删除

#### Scenario: 更新知识块元数据

- **WHEN** 知识块的 category 或 metadata 发生变更
- **THEN** 系统 upsert Milvus entity，更新对应字段

### Requirement: Milvus 索引实现适配抽象接口

系统 SHALL 实现 `MilvusVectorIndex(VectorIndex)` 和 `MilvusSparseIndex(BM25Index)` 类，匹配已有接口契约，使 `RetrievalPipeline` 和 `IngestionPipeline` 无需修改。

#### Scenario: MilvusVectorIndex 满足 VectorIndex 接口

- **WHEN** 实例化 `MilvusVectorIndex`
- **THEN** 其 `add()`、`delete()`、`search()` 方法签名与 `VectorIndex` ABC 完全一致

#### Scenario: MilvusSparseIndex 满足 BM25Index 接口

- **WHEN** 实例化 `MilvusSparseIndex`
- **THEN** 其 `add()`、`delete()`、`search()` 方法签名与 `BM25Index` ABC 完全一致
