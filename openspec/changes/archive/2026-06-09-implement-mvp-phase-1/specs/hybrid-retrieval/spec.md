## ADDED Requirements

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
系统 SHALL 并行执行向量检索和 BM25 检索，然后使用倒数排名融合（RRF）合并结果。

#### Scenario: 双路检索执行
- **WHEN** 重写后的查询提交检索
- **THEN** 系统应并发调用向量索引 `search(query_embedding, top_k=50)` 和 BM25 索引 `search(keywords 或 rewritten_query, top_k=50)`

#### Scenario: RRF 融合
- **WHEN** 两条检索路径都返回结果
- **THEN** 系统应为每个唯一 chunk 计算 `score = 1/(60 + vector_rank) + 1/(60 + bm25_rank)`，取前 20
- **AND** 保留每个候选的 `score_components.vector`、`score_components.bm25` 和融合分数，供重排、调参和调试使用

#### Scenario: 某 chunk 仅出现在一条路径中
- **WHEN** 某个 chunk 出现在向量结果中但不在 BM25 结果中
- **THEN** 其 RRF 分数仅用向量排名贡献计算，仍可能进入前 20

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
系统 SHALL 返回符合定义 schema 的 SearchResult。

#### Scenario: 响应包含所有必需字段
- **WHEN** 搜索完成
- **THEN** 响应应包含 `search_id`、`query`、`rewritten_query`、`total_count` 和 `results` 数组

#### Scenario: 每个结果包含可供渲染的资源引用
- **WHEN** 结果 chunk 有关联的资源
- **THEN** 结果中的 `asset_refs` 应包含 `asset_id`、`relation`、`storage_uri`（从 Asset 解析）、`caption` 和 `render` 指令
- **AND** 若阶段 1 尚无 `storage_uri`，应保留 `original_uri` 或返回 `storage_uri=null`，不得丢失资源关联关系

#### Scenario: 每个结果包含可追溯的来源引用
- **WHEN** 返回结果 chunk
- **THEN** `source_refs` 应包含至少一个条目，含 `doc_id`、`doc_version`、`element_id` 和 `source_location`

#### Scenario: 每个结果包含评分明细和元数据
- **WHEN** 返回结果 chunk
- **THEN** 每个结果应包含最终 `score`、`score_components`、`asset_refs`、`source_refs` 和 `metadata`
