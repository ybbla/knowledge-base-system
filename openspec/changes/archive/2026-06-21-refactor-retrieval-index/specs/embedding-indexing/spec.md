# Embedding & Indexing (delta)

> 父 spec: `openspec/specs/embedding-indexing/spec.md`

## MODIFIED Requirements

### Requirement: 维护内存 BM25 索引

系统 SHALL 维护一个 BM25 索引，支持添加、删除和关键词搜索操作。索引后端为 Milvus（`MILVUS_ENABLED=true`，使用 Milvus 原生 BM25 Function + SPARSE_INVERTED_INDEX + BM25 度量）。内存后端（`MemoryBM25Index`）已移除。

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

系统 SHALL 定义抽象基类 `VectorIndex` 和 `BM25Index`，实现类为 `MilvusVectorIndex` 和 `MilvusBM25Index`。`MemoryBM25Index` 已移除。

#### Scenario: Milvus 实现满足接口
- **WHEN** 实例化 `MilvusVectorIndex` 或 `MilvusBM25Index`
- **THEN** 它们应实现各自抽象基类中定义的所有方法

### Requirement: 向索引添加向量

系统 SHALL 将向量和完整 chunk 元数据写入索引。元数据字段包含 `chunk_id`、`content`、`title`、`category`、`knowledge_type`、`status`、`asset_refs`、`source_refs`、`metadata`、`doc_id`、`created_at`、`updated_at`。

#### Scenario: 向索引添加向量
- **WHEN** 为 chunk 生成了嵌入向量
- **THEN** 向量以 `chunk_id` 为键添加到 Milvus Collection，并保存上述全部元数据字段
- **AND** `sparse_vector` 由 BM25 Function 自动生成

## REMOVED Requirements

> 无。现有 embedding 流程（火山 Embedding → dense 向量）不变。BM25 维护方式变更已在上方 MODIFIED 中覆盖。
