# Hybrid Retrieval

## Purpose

将用户查询重写后执行双路检索（向量 + BM25），通过 RRF 融合和 LLM 重排返回精准排序的 SearchResult。本次更新：检索过滤改为 `filters.category`，SearchResultItem 新增 `category` 和 `knowledge_type` 顶层字段。

> 同步自 change `align-data-model-and-api-with-updated-design`。

## MODIFIED Requirements

### Requirement: 双路检索与混合融合

系统 SHALL 并行执行向量检索和 BM25 检索，支持按 `category` 过滤，然后使用倒数排名融合（RRF）合并结果。

#### Scenario: 双路检索执行

- **WHEN** 重写后的查询提交检索
- **THEN** 系统应并发调用向量索引 `search(query_embedding, top_k=50)` 和 BM25 索引 `search(keywords 或 rewritten_query, top_k=50)`

#### Scenario: 按 category 过滤

- **WHEN** 检索请求包含 `filters.category`
- **THEN** 向量检索和 BM25 检索均仅返回 `category` 匹配的 chunk

#### Scenario: RRF 融合

- **WHEN** 两条检索路径都返回结果
- **THEN** 系统应为每个唯一 chunk 计算 `score = 1/(60 + vector_rank) + 1/(60 + bm25_rank)`，取前 20
- **AND** 保留每个候选的 `score_components.vector`、`score_components.bm25` 和融合分数，供重排、调参和调试使用

#### Scenario: 某 chunk 仅出现在一条路径中

- **WHEN** 某个 chunk 出现在向量结果中但不在 BM25 结果中
- **THEN** 其 RRF 分数仅用向量排名贡献计算，仍可能进入前 20

### Requirement: SearchResult 响应符合数据模型

系统 SHALL 返回符合定义 schema 的 SearchResult，每个结果包含 `category` 和 `knowledge_type` 顶层字段。

#### Scenario: 响应包含所有必需字段

- **WHEN** 搜索完成
- **THEN** 响应应包含 `search_id`、`query`、`rewritten_query`、`total_count` 和 `results` 数组

#### Scenario: 每个结果包含 category 和 knowledge_type

- **WHEN** 返回结果 chunk
- **THEN** 每个结果应包含顶层字段 `category`（继承自 KnowledgeChunk）和 `knowledge_type`

#### Scenario: 每个结果包含可供渲染的资源引用

- **WHEN** 结果 chunk 有关联的资源
- **THEN** 结果中的 `asset_refs` 应包含 `asset_id`、`relation`、`storage_uri`（从 Asset 解析）、`caption` 和 `render` 指令
- **AND** 若阶段 1 尚无 `storage_uri`，应保留 `original_uri` 或返回 `storage_uri=null`，不得丢失资源关联关系

#### Scenario: 每个结果包含可追溯的来源引用

- **WHEN** 返回结果 chunk
- **THEN** `source_refs` 应包含至少一个条目，含 `doc_id`、`doc_version`、`element_id` 和 `source_location`

#### Scenario: 每个结果包含评分明细和元数据

- **WHEN** 返回结果 chunk
- **THEN** 每个结果应包含最终 `score`、`score_components`、`category`、`knowledge_type`、`asset_refs`、`source_refs` 和 `metadata`
