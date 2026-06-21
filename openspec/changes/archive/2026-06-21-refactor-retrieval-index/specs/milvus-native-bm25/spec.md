# Milvus Native BM25

## Purpose

使用 Milvus 2.5 原生 BM25 Function 替代自定义 jieba + TF-IDF 稀疏向量生成。利用 Milvus 内置 Tantivy 引擎和 `chinese` 分析器实现真正的 BM25(k1,b) 全文检索，消除应用层分词和 IDF 统计对 PostgreSQL 的依赖。

## ADDED Requirements

### Requirement: BM25 Function 自动生成稀疏向量

系统 SHALL 在 Milvus Collection 的 `content` 字段上启用分析器（`enable_analyzer=True`，`analyzer_params={"type": "chinese"}`），并通过 `Function(FunctionType.BM25)` 将 `content` 自动映射为 `sparse_vector` 字段。用户仅需写入原始文本，BM25 稀疏向量由 Milvus 自动生成和维护。

#### Scenario: 创建 Collection 时配置 BM25 Function
- **WHEN** Milvus Collection 首次创建
- **THEN** `content` 字段设置 `enable_analyzer=True` 和 `analyzer_params={"type": "chinese"}`
- **AND** Collection schema 包含 `Function(name="bm25", function_type=FunctionType.BM25, input_field_names=["content"], output_field_names="sparse_vector")`

#### Scenario: 写入 chunk 时自动生成 BM25 向量
- **WHEN** 向 Milvus 写入或 upsert 一个包含 `content` 的 entity
- **THEN** Milvus 自动对 `content` 执行中文分词和 BM25 统计，生成稀疏向量存入 `sparse_vector`
- **AND** 无需在应用层调用 jieba 分词或 TF-IDF 编码

#### Scenario: 旧 schema 自动检测并迁移
- **WHEN** Collection 已存在但未配置 BM25 Function（旧 schema）
- **THEN** 系统检测到 schema 不含 `FunctionType.BM25`，自动 drop 并重建 Collection

### Requirement: 原生 BM25 关键词检索

系统 SHALL 通过直接传入原始查询文本到 `collection.search(anns_field="sparse_vector", metric_type="BM25")` 执行 BM25 检索，无需应用层编码稀疏向量。

#### Scenario: BM25 检索直接接受原始文本
- **WHEN** 提交 BM25 检索请求
- **THEN** 查询参数为原始文本字符串（如 `"如何上传文档"`），而非 `{token_id: weight}` 稀疏向量
- **AND** Milvus 使用 BM25 Function 定义的分析器自动分词并计算匹配分数

#### Scenario: BM25 检索支持过滤和排序
- **WHEN** BM25 检索附带 `category` 和 `status` 过滤条件
- **THEN** search expr 包含 `(status == "active")` 及可选的 `(category == "...")`
- **AND** 返回按 BM25 分数降序排列的 top_k 结果

#### Scenario: 中文分词准确性
- **WHEN** 查询文本为中文
- **THEN** `chinese` 分析器正确分词，对中文特有语法结构（词组、单字组合）产生合理 BM25 匹配

### Requirement: BM25Index 抽象接口的 Milvus 实现

系统 SHALL 提供 `MilvusBM25Index(BM25Index)` 类实现 `BM25Index` 抽象接口，与 `MilvusVectorIndex` 共享同一个 `MilvusCollectionManager` 实例。

#### Scenario: add_batch 写入 content 和标量字段
- **WHEN** 调用 `MilvusBM25Index.add_batch(items)`
- **THEN** items 中的 `content` 和标量字段（`category`、`status`、`knowledge_type` 等）写入 Milvus Collection
- **AND** `sparse_vector` 由 BM25 Function 自动生成，无需应用层编码

#### Scenario: search 返回 (chunk_id, score) 列表
- **WHEN** 调用 `MilvusBM25Index.search(query, top_k, category)`
- **THEN** 系统直接传入原始查询文本，不进行应用层分词
- **AND** 返回 `list[tuple[str, float]]` 格式，与 `BM25Index` 接口一致

### Requirement: 移除自定义 BM25 实现

系统 SHALL 删除 `MilvusSparseIndex`（jieba + TF-IDF 手动编码）、`MemoryBM25Index`（内存 rank_bm25）、PostgreSQL `idf_stats` 表及 `DbIdfStat` ORM 模型。

#### Scenario: 旧实现完全替代
- **WHEN** 新 BM25 实现部署后
- **THEN** 所有 BM25 检索通过 `MilvusBM25Index` 完成
- **AND** 不再有代码引用 `MilvusSparseIndex`、`MemoryBM25Index` 或 `DbIdfStat`
