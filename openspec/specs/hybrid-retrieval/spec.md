# Hybrid Retrieval

## Purpose

将用户查询重写后执行双路检索（向量 + BM25），在 Milvus 可用时通过 Milvus Hybrid Search 原生融合，在不可用时通过应用层 RRF 融合，并经 LLM 重排返回精准排序的 SearchResult。检索过滤使用 `filters.category`，SearchResultItem 包含 `category` 和 `knowledge_type` 顶层字段。

> 同步自 change `implement-mvp-phase-1`，日期 2026-06-09；更新自 change `align-data-model-and-api-with-updated-design`，日期 2026-06-10；更新自 change `phase-3-milvus-minio`，日期 2026-06-12。

## Requirements

### Requirement: 重写用户查询以供检索

系统 SHALL 将用户的原始问题重写为适合向量检索和关键词检索的形式，保留原始意图。

#### Scenario: 省略主语的查询

- **WHEN** 用户提交 `上传之后怎么知道成功了没？`
- **THEN** 重写后的查询应补全省略的主语和对象，例如 `用户上传知识文档后，如何查看文档解析状态，以及如何判断解析成功或失败？`

#### Scenario: 提取关键词

- **WHEN** 查询被重写时
- **THEN** 输出应包含提取的 `keywords`（供 BM25 检索使用）和 `intent`（供日志记录）

#### Scenario: LLM 不回答问题

- **WHEN** LLM 重写查询时
- **THEN** 输出不得包含对用户问题的回答——仅为重写后的查询

#### Scenario: JSON 输出校验

- **WHEN** LLM 返回重写查询 JSON
- **THEN** 系统校验其包含 `rewritten_query`、`keywords` 和 `intent` 字段；失败时最多重试 3 次

### Requirement: 双路检索与混合融合

系统 SHALL 并行执行向量检索和 BM25 检索，支持按 `category` 过滤，然后融合结果。当 Milvus 可用时使用 Milvus `hybrid_search()` API + `RRFRanker` 原生融合；当 Milvus 不可用或 Hybrid Search 失败时分别调用向量/BM25 检索并在应用层执行 RRF 融合。检索参数（`vector_top_k`、`bm25_top_k`、`fusion_top_k`、`rrf_k`）均可通过配置修改。

#### Scenario: 双路检索执行

- **WHEN** 重写后的查询提交检索
- **THEN** 系统应执行密集向量查询和关键词查询（在 Milvus 内或分别调用两种索引），各取 top 50（可配置）

#### Scenario: 按 category 过滤

- **WHEN** 检索请求包含 `filters.category`
- **THEN** 向量检索和 BM25 检索均仅返回 `category` 匹配的 chunk

#### Scenario: Milvus Hybrid Search 融合（默认路径）

- **WHEN** Milvus 可用且两条检索路径都有结果
- **THEN** 系统通过 Milvus `hybrid_search()` + `RRFRanker(k)` 在 Milvus 内部完成双路分数融合，返回排序后的 top_k 结果
- **AND** `score_components.vector`（dense 分数）和 `score_components.bm25`（sparse 分数）通过额外单路查询获取，用于解释、调参和调试

#### Scenario: 应用层 RRF 融合（fallback 路径）

- **WHEN** Milvus 不可用或 Hybrid Search 失败
- **THEN** 系统为每个唯一 chunk 计算 `score = 1/(rrf_k + vector_rank) + 1/(rrf_k + bm25_rank)`，取前 `fusion_top_k`
- **AND** 保留每个候选的 `score_components.vector`、`score_components.bm25` 和融合分数

#### Scenario: 某 chunk 仅出现在一条路径中

- **WHEN** 某个 chunk 出现在向量结果中但不在 BM25 结果中（或反之）
- **THEN** 其融合分数仅用出现路径的排名贡献计算，仍可能进入融合结果

#### Scenario: 检索参数可配置

- **WHEN** 管理员修改 `VECTOR_TOP_K`、`BM25_TOP_K`、`FUSION_TOP_K` 或 `RRF_K` 配置值
- **THEN** 下次检索使用新参数值，无需重启服务

### Requirement: LLM 重排融合候选

系统 SHALL 使用 LLM 结合原始用户查询对前 20 个融合候选进行重排。

#### Scenario: 重排产生有序结果

- **WHEN** 将 20 个候选 chunk 和原始查询发送给 LLM 重排器
- **THEN** 输出应包含按 `relevance_score` 降序排列的 chunk，每个附带解释相关性的 `reason`

#### Scenario: 重排器仅判断相关性

- **WHEN** LLM 重排候选时
- **THEN** LLM 不得回答用户问题或添加候选 chunk 中不存在的信息

#### Scenario: 返回最终 top-k

- **WHEN** 重排完成
- **THEN** 前 `top_k` 个 chunk（默认 5，通常 5 到 10）在 SearchResult 响应中返回

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
