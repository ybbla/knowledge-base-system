# Embedding & Indexing

## Purpose

为 KnowledgeChunk 生成向量嵌入，维护内存向量索引和 BM25 索引，支持添加、删除和相似度/关键词搜索。

> 同步自 change `implement-mvp-phase-1`，日期 2026-06-09。

## Requirements

### Requirement: 为 KnowledgeChunk 生成向量嵌入

系统 SHALL 为每个 KnowledgeChunk 生成向量嵌入，直接将 `KnowledgeChunk.content` 发送给嵌入模型；`title_path`、`knowledge_type`、文档状态和语言等字段只作为索引元数据、过滤条件、BM25 或重排输入。

#### Scenario: 为知识块生成嵌入

- **WHEN** 创建了一个 KnowledgeChunk，其 `title_path=["用户手册","上传文档"]`、`content="...上传文档后...状态..."`、`knowledge_type="declarative"`
- **THEN** 嵌入输入文本为 `...上传文档后...状态...`，并返回浮点向量
- **AND** `title_path` 和 `knowledge_type` 作为索引元数据保存，不参与 embedding 输入

#### Scenario: 批量嵌入

- **WHEN** 一个文档生成了多个 chunk
- **THEN** 系统可将多个 `content` 文本通过 `EmbeddingClient.embed_text(texts)` 批量发送给嵌入模型

### Requirement: 维护内存向量索引

系统 SHALL 维护一个内存向量索引，支持添加、删除和相似度搜索操作。

#### Scenario: 向索引添加向量

- **WHEN** 为 chunk 生成了嵌入向量
- **THEN** 向量以 `chunk_id` 为键添加到内存索引中，并保存 `doc_id`、`knowledge_type`、`title_path`、`source_refs`、`asset_refs` 和 `metadata` 等元数据

#### Scenario: 相似度搜索返回 top-k

- **WHEN** 以 `top_k=50` 提交查询嵌入
- **THEN** 索引返回按余弦相似度排序的前 50 个 `chunk_id`

#### Scenario: 从索引删除向量

- **WHEN** 一个 chunk 被删除或替代
- **THEN** 其向量从索引中移除

### Requirement: 维护内存 BM25 索引

系统 SHALL 维护一个内存 BM25 索引，支持添加、删除和关键词搜索操作。

#### Scenario: 向 BM25 索引添加文档

- **WHEN** 创建了一个包含中文文本的 KnowledgeChunk
- **THEN** `content` 文本经过分词后以 `chunk_id` 为键添加到 BM25 索引

#### Scenario: BM25 搜索返回 top-k

- **WHEN** 以 `top_k=50` 提交关键词查询
- **THEN** 索引返回按 BM25 分数排序的前 50 个 `chunk_id`

#### Scenario: BM25 处理精确词匹配

- **WHEN** 查询包含通用文本中少见的专业术语或错误码
- **THEN** BM25 应将包含这些精确词的 chunk 排在仅语义相似的 chunk 之上

### Requirement: 索引接口抽象存储后端

系统 SHALL 定义抽象基类 `VectorIndex` 和 `BM25Index`，以便后续用 Milvus 替换内存实现而不修改调用方。

#### Scenario: 内存实现满足接口

- **WHEN** 实例化 `MemoryVectorIndex` 或 `MemoryBM25Index`
- **THEN** 它们应实现各自抽象基类中定义的所有方法
