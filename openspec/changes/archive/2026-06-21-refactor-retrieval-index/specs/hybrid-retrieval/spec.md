# Hybrid Retrieval (delta)

> 父 spec: `openspec/specs/hybrid-retrieval/spec.md`

## MODIFIED Requirements

### Requirement: 双路检索与混合融合

系统 SHALL 并行执行向量检索和 BM25 检索，支持按 category、knowledge_type 和 status 在 Milvus expr 中做索引级过滤，然后通过应用层 `rrf_fusion()` 融合结果。两路检索共享同一个 `MilvusCollectionManager`，但各自独立调用 `collection.search()`，使用 `ThreadPoolExecutor` 实现并行。检索参数（`vector_top_k`、`bm25_top_k`、`fusion_top_k`、`rrf_k`）均可通过配置修改。融合后的 chunk 详情直接从 Milvus search 的 `output_fields` 获取，不再依赖 PostgreSQL。

#### Scenario: 双路检索并行执行
- **WHEN** 重写后的查询提交检索
- **THEN** 系统并行发起两路独立请求：`vector_index.search(query_vec, top_k)` 和 `bm25_index.search(keywords_str, top_k)`
- **AND** 两路 search 的 `output_fields` 均包含完整的 chunk 字段（`chunk_id`、`content`、`title`、`category`、`knowledge_type`、`asset_refs`、`source_refs`、`metadata`、`doc_id`、`created_at`、`updated_at`）

#### Scenario: 按单一 category 过滤
- **WHEN** 检索请求包含 `filters.categories` 且仅有一个值
- **THEN** 向量检索和 BM25 检索的 Milvus expr 均包含 `category == "value"`

#### Scenario: 按 knowledge_type 过滤
- **WHEN** 检索请求包含 `filters.knowledge_types` 且仅有一个值
- **THEN** 向量检索和 BM25 检索的 Milvus expr 均包含 `knowledge_type == "value"`

#### Scenario: 按多个 categories 过滤
- **WHEN** 检索请求包含 `filters.categories` 且有多个值（如 `["技术", "产品"]`）
- **THEN** 系统 SHALL 对每个 category 分别执行检索，合并去重后按分数排序
- **AND** 返回的每个 chunk 的 `category` SHALL 属于 `filters.categories` 中的某个值

#### Scenario: 应用层 RRF 融合（唯一路径）
- **WHEN** 两路检索都有结果
- **THEN** 系统为每个唯一 chunk 计算 `score = 1/(rrf_k + vector_rank) + 1/(rrf_k + bm25_rank)`，取前 `fusion_top_k`
- **AND** 融合后的 chunk 详情直接从 search 返回的 entity 中获取，无需查询 PostgreSQL

#### Scenario: 某 chunk 仅出现在一条路径中
- **WHEN** 某个 chunk 出现在向量结果中但不在 BM25 结果中（或反之）
- **THEN** 其融合分数仅用出现路径的排名贡献计算，仍可能进入融合结果

#### Scenario: 检索参数可配置
- **WHEN** 管理员修改 `VECTOR_TOP_K`、`BM25_TOP_K`、`FUSION_TOP_K` 或 `RRF_K` 配置值
- **THEN** 下次检索使用新参数值，无需重启服务

### Requirement: 系统提供检索调试信息

系统 SHALL 通过 `POST /api/v1/search/debug` 返回检索链路中的查询改写、关键词、过滤条件、向量候选、BM25 候选、融合候选和 Rerank 结果。调试响应不再包含 `used_milvus_hybrid` 字段。

#### Scenario: 调试检索返回分阶段候选
- **WHEN** 客户端请求调试检索
- **THEN** 响应 SHALL 包含 `rewrite`、`vector_candidates`、`bm25_candidates`、`fused_candidates` 和 `rerank_results`
- **AND** 响应 SHALL NOT 包含 `used_milvus_hybrid`

#### Scenario: 调试检索不泄露敏感信息
- **WHEN** 检索链路出现异常
- **THEN** 调试响应 SHALL 返回错误摘要
- **AND** 响应 MUST NOT 包含密钥、完整提示词或底层堆栈

## REMOVED Requirements

### Requirement: Milvus Hybrid Search 融合（默认路径）

**Reason**: 两路并行 + 应用层 RRF 替代。消除 Hybrid Search 成功/失败的 branching，检索逻辑统一为外部 RRF 一条路径。

**Migration**: 删除 `indexing/milvus_hybrid.py`。`retrieval/pipeline.py` 中 `hybrid_results` 分支和相关 fallback 逻辑全部移除。

### Requirement: SearchResult 每个结果包含评分明细和元数据

**Reason**: 此 requirement 中"从 PostgreSQL 获取 chunk 详情"的描述已过时。chunk 详情现直接从 Milvus search `output_fields` 获取。

**Migration**: `retrieval/pipeline.py` 中 `chunk_store.get_batch()` 调用替换为从 search 返回的 entity 数据直接构建。
