# Embedding & Indexing

## Purpose

为 KnowledgeChunk 生成向量嵌入，维护内存向量索引和 BM25 索引，支持添加、删除和按 `category`/`knowledge_type` 过滤的搜索。

> 同步自 change `align-data-model-and-api-with-updated-design`。

## MODIFIED Requirements

### Requirement: 为 KnowledgeChunk 生成向量嵌入

系统 SHALL 为每个 KnowledgeChunk 生成向量嵌入，直接将 `KnowledgeChunk.content` 发送给嵌入模型；`category`、`knowledge_type`、`title_path`、文档状态和语言等字段只作为索引元数据、过滤条件、BM25 或重排输入，不进入 embedding 输入。

#### Scenario: 为知识块生成嵌入

- **WHEN** 创建了一个 KnowledgeChunk，其 `category="产品使用"`、`title_path=["用户手册","上传文档"]`、`content="...上传文档后...状态..."`、`knowledge_type="declarative"`
- **THEN** 嵌入输入文本为 `...上传文档后...状态...`，并返回浮点向量
- **AND** `category`、`title_path` 和 `knowledge_type` 作为索引元数据保存，不参与 embedding 输入

#### Scenario: 批量嵌入

- **WHEN** 一个文档生成了多个 chunk
- **THEN** 系统可将多个 `content` 文本通过 `EmbeddingClient.embed_text(texts)` 批量发送给嵌入模型

### Requirement: 维护内存向量索引

系统 SHALL 维护一个内存向量索引，支持添加、删除和相似度搜索，元数据中包含 `category` 以支持过滤。

#### Scenario: 向索引添加向量

- **WHEN** 为 chunk 生成了嵌入向量
- **THEN** 向量以 `chunk_id` 为键添加到内存索引中，并保存 `doc_id`、`category`、`knowledge_type`、`title_path`、`source_refs`、`asset_refs` 和 `metadata` 等元数据

#### Scenario: 相似度搜索返回 top-k

- **WHEN** 以 `top_k=50` 提交查询嵌入
- **THEN** 索引返回按余弦相似度排序的前 50 个 `chunk_id`

#### Scenario: 按 category 过滤搜索

- **WHEN** 提交查询时附带 `category` 过滤条件
- **THEN** 仅返回 `category` 匹配的 chunk，其他 chunk 被排除

#### Scenario: 从索引删除向量

- **WHEN** 一个 chunk 被删除或替代
- **THEN** 其向量从索引中移除
