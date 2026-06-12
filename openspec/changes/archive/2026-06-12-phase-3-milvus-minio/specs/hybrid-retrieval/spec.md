# Hybrid Retrieval (Delta)

Delta spec 基于 `openspec/specs/hybrid-retrieval/spec.md`，变更双路检索融合策略——Milvus Hybrid Search 原生融合作为默认路径，应用层 RRF 作为 fallback。检索参数改为可配置。

## MODIFIED Requirements

### Requirement: 双路检索与混合融合

系统 SHALL 并行执行向量检索和 BM25 检索，支持按 `category` 过滤，然后融合结果。当 Milvus 可用时使用 Milvus `hybrid_search()` API + `RRFRanker` 原生融合；当 Milvus 不可用时分别调用向量/BM25 检索并在应用层执行 RRF 融合。检索参数（`vector_top_k`、`bm25_top_k`、`fusion_top_k`、`rrf_k`）均可通过配置修改。

#### Scenario: 双路检索执行

- **WHEN** 重写后的查询提交检索
- **THEN** 系统应执行密集向量查询和关键词查询（在 Milvus 内或分别调用两种索引），各取 top 50（可配置）

#### Scenario: 按 category 过滤

- **WHEN** 检索请求包含 `filters.category`
- **THEN** 向量检索和 BM25 检索均仅返回 `category` 匹配的 chunk

#### Scenario: Milvus Hybrid Search 融合（默认路径）

- **WHEN** Milvus 可用且两条检索路径都有结果
- **THEN** 系统通过 Milvus `hybrid_search()` + `RRFRanker(k)` 在 Milvus 内部完成双路分数融合，返回排序后的 top_k 结果
- **AND** `score_components.vector`（dense 分数）和 `score_components.bm25`（sparse 分数）可通过额外查询获取

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
