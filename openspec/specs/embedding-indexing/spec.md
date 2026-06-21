# Embedding & Indexing

## Purpose

为 KnowledgeChunk 生成向量嵌入，维护向量索引（HNSW + COSINE）和 BM25 索引（Milvus 原生 BM25 Function + chinese 分析器），支持添加、删除和按 `category`/`knowledge_type` 过滤的搜索。索引后端为 Milvus；BM25 稀疏向量由 Milvus 自动生成，不再依赖 jieba 分词和 PostgreSQL IDF 统计。

> 同步自 change `implement-mvp-phase-1`，日期 2026-06-09；更新自 change `align-data-model-and-api-with-updated-design`，日期 2026-06-10；更新自 change `phase-3-milvus-minio`，日期 2026-06-12；更新自 change `refactor-retrieval-index`，日期 2026-06-21。

## Requirements

### Requirement: 为 KnowledgeChunk 生成向量嵌入

系统 SHALL 为每个 KnowledgeChunk 生成向量嵌入，直接将 `KnowledgeChunk.content` 发送给嵌入模型；`category`、`knowledge_type`、`title_path`、文档状态和语言等字段只作为索引元数据、过滤条件、BM25 或重排输入，不进入 embedding 输入。

#### Scenario: 为知识块生成嵌入

- **WHEN** 创建了一个 KnowledgeChunk，其 `category="产品使用"`、`title="上传文档"`、`content="...上传文档后...状态..."`、`knowledge_type="declarative"`
- **THEN** 嵌入输入文本为 `...上传文档后...状态...`，并返回浮点向量
- **AND** `category`、`title` 和 `knowledge_type` 作为索引元数据保存，不参与 embedding 输入

#### Scenario: 批量嵌入

- **WHEN** 一个文档生成了多个 chunk
- **THEN** 系统可将多个 `content` 文本通过 `EmbeddingClient.embed_text(texts)` 批量发送给嵌入模型

### Requirement: 维护向量索引

系统 SHALL 维护一个向量索引（Milvus HNSW + COSINE），支持添加、删除和相似度搜索，元数据中包含 `category` 和 `knowledge_type` 以支持过滤。

#### Scenario: 向索引添加向量

- **WHEN** 为 chunk 生成了嵌入向量
- **THEN** 向量以 `chunk_id` 为键添加到 Milvus Collection，并保存 `doc_id`、`title`、`content`、`category`、`knowledge_type`、`status`、`asset_refs`、`source_refs`、`metadata`、`created_at`、`updated_at` 等元数据
- **AND** `sparse_vector` 由 BM25 Function 自动生成

#### Scenario: 相似度搜索返回 top-k

- **WHEN** 以 `top_k` 提交查询嵌入
- **THEN** 索引返回按余弦相似度排序的前 top_k 个 `chunk_id`

#### Scenario: 按 category 和 knowledge_type 过滤搜索

- **WHEN** 提交查询时附带 `category` 和 `knowledge_type` 过滤条件
- **THEN** Milvus expr 包含对应过滤条件，仅返回匹配 chunk

#### Scenario: 从索引删除向量

- **WHEN** 一个 chunk 被删除或替代
- **THEN** 其向量从索引中移除或状态同步为 deleted

#### Scenario: 索引持久化——服务重启数据保留

- **WHEN** 使用 Milvus 后端（`MILVUS_ENABLED=true`）且服务重启
- **THEN** 索引数据在 Milvus 中完整保留，无需重新 embedding 即可恢复检索能力

### Requirement: 维护 BM25 索引

系统 SHALL 维护一个 BM25 索引（Milvus 原生 BM25 Function + SPARSE_INVERTED_INDEX + BM25 度量），支持添加、删除和关键词搜索操作。

#### Scenario: 向 BM25 索引添加文档

- **WHEN** 创建了一个包含中文文本的 KnowledgeChunk
- **THEN** `content` 和标量字段写入 Milvus Collection，Milvus BM25 Function 自动对 content 执行 `chinese` 分析器分词并生成稀疏向量
- **AND** 无需在应用层调用 jieba 分词或 TF-IDF 编码

#### Scenario: BM25 搜索返回 top-k

- **WHEN** 以 `top_k` 提交关键词查询
- **THEN** 索引返回按 BM25 分数排序的前 top_k 个 `chunk_id` 及完整 chunk 数据
- **AND** 查询参数为原始文本字符串，非稀疏向量

#### Scenario: BM25 处理精确词匹配

- **WHEN** 查询包含通用文本中少见的专业术语或错误码
- **THEN** BM25 应将包含这些精确词的 chunk 排在仅语义相似的 chunk 之上

#### Scenario: BM25 索引持久化——服务重启数据保留

- **WHEN** 使用 Milvus 后端（`MILVUS_ENABLED=true`）且服务重启
- **THEN** BM25 稀疏向量在 Milvus 中完整保留，无需重建索引
- **AND** 不再依赖 PostgreSQL `idf_stats` 表

### Requirement: 索引接口抽象存储后端

系统 SHALL 定义抽象基类 `VectorIndex` 和 `BM25Index`，实现类为 `MilvusVectorIndex` 和 `MilvusBM25Index`。

#### Scenario: Milvus 实现满足接口

- **WHEN** 实例化 `MilvusVectorIndex` 或 `MilvusBM25Index`
- **THEN** 它们应实现各自抽象基类中定义的所有方法
