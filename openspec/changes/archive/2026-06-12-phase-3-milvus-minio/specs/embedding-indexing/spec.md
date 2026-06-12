# Embedding & Indexing (Delta)

Delta spec 基于 `openspec/specs/embedding-indexing/spec.md`，变更索引存储后端从进程内存到 Milvus（可选回退内存）。

## MODIFIED Requirements

### Requirement: 维护内存向量索引

系统 SHALL 维护一个向量索引，支持添加、删除和相似度搜索，元数据中包含 `category` 以支持过滤。索引后端可为 Milvus（`MILVUS_ENABLED=true`）或进程内存（`MILVUS_ENABLED=false`），通过 `VectorIndex` 抽象接口切换。

#### Scenario: 向索引添加向量

- **WHEN** 为 chunk 生成了嵌入向量
- **THEN** 向量以 `chunk_id` 为键添加到当前后端索引中（Milvus Collection 或内存 numpy 数组），并保存 `doc_id`、`category`、`knowledge_type`、`title_path`、`source_refs`、`asset_refs` 和 `metadata` 等元数据

#### Scenario: 相似度搜索返回 top-k

- **WHEN** 以 `top_k=50` 提交查询嵌入
- **THEN** 索引返回按相似度排序的前 50 个 `chunk_id`（Milvus 使用 IP 距离，内存使用余弦相似度）

#### Scenario: 按 category 过滤搜索

- **WHEN** 提交查询时附带 `category` 过滤条件
- **THEN** 仅返回 `category` 匹配的 chunk，其他 chunk 被排除

#### Scenario: 从索引删除向量

- **WHEN** 一个 chunk 被删除或替代
- **THEN** 其向量从索引中移除

#### Scenario: 索引持久化——服务重启数据保留

- **WHEN** 使用 Milvus 后端（`MILVUS_ENABLED=true`）且服务重启
- **THEN** 索引数据在 Milvus 中完整保留，无需重新 embedding 即可恢复检索能力

### Requirement: 维护内存 BM25 索引

系统 SHALL 维护一个 BM25 索引，支持添加、删除和关键词搜索操作。索引后端可为 Milvus sparse vector（`MILVUS_ENABLED=true`，jieba 分词 + TF-IDF 编码）或进程内存（`MILVUS_ENABLED=false`，jieba + rank_bm25），通过 `BM25Index` 抽象接口切换。

#### Scenario: 向 BM25 索引添加文档

- **WHEN** 创建了一个包含中文文本的 KnowledgeChunk
- **THEN** `content` 文本经过 jieba 分词后以 `chunk_id` 为键添加到 BM25 索引（Milvus sparse vector 或内存 rank_bm25 corpus）

#### Scenario: BM25 搜索返回 top-k

- **WHEN** 以 `top_k=50` 提交关键词查询
- **THEN** 索引返回按 BM25 分数排序的前 50 个 `chunk_id`

#### Scenario: BM25 处理精确词匹配

- **WHEN** 查询包含通用文本中少见的专业术语或错误码
- **THEN** BM25 应将包含这些精确词的 chunk 排在仅语义相似的 chunk 之上

#### Scenario: BM25 索引持久化——服务重启数据保留

- **WHEN** 使用 Milvus 后端（`MILVUS_ENABLED=true`）且服务重启
- **THEN** 全局 IDF 和 sparse vector 数据在 Milvus/PostgreSQL 中完整保留，无需重建索引
