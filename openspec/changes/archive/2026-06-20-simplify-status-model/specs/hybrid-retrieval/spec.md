# Hybrid Retrieval (Delta)

## MODIFIED Requirements

### Requirement: 双路检索与混合融合

系统 SHALL 并行执行向量检索和 BM25 检索，支持按文档、分类、来源类型、知识类型、文档状态、知识块状态和时间范围过滤，然后融合结果。当 `filters.categories` 包含单个值时，系统 SHALL 将该值传给检索管道作为索引级过滤；当 `filters.categories` 包含多个值或为 `None` 时，系统 SHALL 对每个 category 分别执行检索后合并去重（按 chunk_id 去重，保留最高分），确保所有指定分类的相关结果均能被召回。当 Milvus 可用时使用 Milvus `hybrid_search()` API + `RRFRanker` 原生融合；当 Milvus 不可用或 Hybrid Search 失败时分别调用向量/BM25 检索并在应用层执行 RRF 融合。检索参数（`vector_top_k`、`bm25_top_k`、`fusion_top_k`、`rrf_k`）均可通过配置修改。

#### Scenario: 双路检索执行
- **WHEN** 重写后的查询提交检索
- **THEN** 系统应执行密集向量查询和关键词查询（在 Milvus 内或分别调用两种索引），各取 top 50（可配置）

#### Scenario: 按单一 category 过滤
- **WHEN** 检索请求包含 `filters.categories` 且仅有一个值
- **THEN** 向量检索和 BM25 检索均仅返回 `category` 等于该值的 chunk

#### Scenario: 按多个 categories 过滤
- **WHEN** 检索请求包含 `filters.categories` 且有多个值（如 `["技术", "产品"]`）
- **THEN** 系统 SHALL 对每个 category 分别执行检索，合并去重后按分数排序
- **AND** 返回的每个 chunk 的 `category` SHALL 属于 `filters.categories` 中的某个值
- **AND** 所有指定分类的候选结果 SHALL 在合并结果中得到公平体现

#### Scenario: 无 category 过滤
- **WHEN** 检索请求未包含 `filters.categories` 或其值为空列表/`None`
- **THEN** 检索不对 category 做索引级过滤，返回所有分类的候选结果

#### Scenario: 按文档和知识类型过滤
- **WHEN** 检索请求包含 `filters.doc_ids` 和 `filters.knowledge_types`
- **THEN** 系统仅返回指定文档范围内且知识类型匹配的 chunk

#### Scenario: 按状态过滤
- **WHEN** 检索请求包含 `filters.chunk_status=["active"]`
- **THEN** 系统仅返回业务状态为 `active` 的 chunk

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

### Requirement: 系统提供检索筛选项

系统 SHALL 通过 `GET /api/v1/search/filters` 返回前端可展示的分类、来源类型、知识类型、文档状态和知识块状态筛选项。筛选项的 `count` 值 SHALL 优先使用 document_repo 统计（覆盖所有文档），仅当 document_repo 不可用时回退到 chunk_store 统计，不使用两种数据源的混合值。

#### Scenario: 获取筛选项
- **WHEN** 客户端请求检索筛选项
- **THEN** 系统返回可用 `categories`、`source_types`、`knowledge_types`、`doc_statuses` 和 `chunk_statuses`

#### Scenario: 筛选项包含计数
- **WHEN** 筛选项来自可统计字段
- **THEN** 每个筛选项 SHOULD 包含 `value` 和 `count`

#### Scenario: 分类计数优先使用文档仓储
- **GIVEN** document_repo 可用
- **WHEN** 客户端请求检索筛选项
- **THEN** categories 的 `count` SHALL 来自 document_repo 的分类统计
- **AND** 统计 SHALL 覆盖所有文档（含尚无知识块的新文档），而非仅覆盖已有知识块的文档

#### Scenario: 文档仓储不可用时回退到知识块统计
- **GIVEN** document_repo 不可用（内存模式）
- **WHEN** 客户端请求检索筛选项
- **THEN** categories 的 `count` SHALL 来自 chunk_store 的分类统计
