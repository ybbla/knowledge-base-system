## Why

当前检索索引层存在三个问题：1) BM25 用 jieba + 应用层 TF-IDF 手动计算稀疏向量而非真正的 BM25 公式，IDF 统计依赖 PostgreSQL `idf_stat` 表；2) Dense 向量索引使用 IVF_FLAT，不如 HNSW 的召回率-速度平衡；3) 检索 pipeline 先搜 Milvus 取 chunk_id，再回 PG 取详情，多一次网络往返。Milvus 2.5.11 已原生支持 BM25 Function（Tantivy 引擎 + 中文分析器）和 HNSW 索引，利用这些能力可大幅简化索引层、提升检索质量并消除不必要的 PG 依赖。

## What Changes

- Dense 索引：IVF_FLAT → **HNSW** + COSINE（M=16, efConstruction=200, ef=64 可配置）
- BM25 索引：自定义 jieba+TF-IDF → Milvus 原生 **Function(BM25)** + `chinese` 分析器，稀疏向量由 Milvus 自动生成
- 融合方式：Milvus `hybrid_search()` + `RRFRanker` → 两路并行 `search()` + 应用层 **`rrf_fusion()`**（删除 `milvus_hybrid.py`）
- 数据获取：检索后 PG `chunk_store.get_batch()` → search 时 `output_fields` 直接带回全部 chunk 字段，消除检索热路径的 PG 查询
- **BREAKING**：Milvus Collection schema 变更——新增 `title`/`updated_at` 字段，删除 `sparse_max_vocab` 配置，删除 `DbIdfStat` ORM 模型，删除 `milvus_sparse.py`/`milvus_hybrid.py`/`memory_bm25.py`
- 检索 pipeline 移除 Milvus hybrid / fallback 分支，简化为统一的并行两路 + 外部 RRF 流程
- **BREAKING**：检索 API 的 debug 响应中移除 `used_milvus_hybrid` 字段

## Capabilities

### New Capabilities

- `milvus-native-bm25`: Milvus 2.5 原生 BM25 全文检索能力，使用 Tantivy 引擎 + 中文分析器，替代自定义 jieba+TF-IDF 稀疏向量
- `hnsw-dense-index`: HNSW 向量索引替代 IVF_FLAT，提供更高的召回率-速度平衡

### Modified Capabilities

- `milvus-indexing`: Collection schema 变更（HNSW + BM25 Function + 字段增删），稀疏索引方法从手动 jieba 改为 Milvus 原生 BM25
- `hybrid-retrieval`: 双路融合从 Milvus `hybrid_search()` + `RRFRanker` 改为两路并行 search + 应用层 `rrf_fusion()`，检索热路径直接从 Milvus `output_fields` 获取 chunk 数据
- `embedding-indexing`: BM25 索引部分不再需要手动 jieba 分词和 TF-IDF 编码，IDF 统计不再写入 PG

## Impact

- **代码**：`indexing/milvus_vector.py`（schema 重构）、`indexing/milvus_bm25.py`（新建）、`retrieval/pipeline.py`（并行+外部 RRF）、`app/core/deps.py`（注入变更）、`app/core/config.py`（新增 HNSW 参数）
- **删除**：`indexing/milvus_hybrid.py`、`indexing/milvus_sparse.py`、`indexing/memory_bm25.py`、`app/db/models.py` 中 `DbIdfStat`
- **测试**：`tests/test_milvus_indexing.py`、`tests/test_batch_indexing.py`、`tests/test_v1_real_endpoints.py`、`tests/test_db_models.py`、`tests/evaluation/tune_params.py`
- **数据迁移**：Collection 需重建（drop + create），从 PG 全量重新索引
- **回滚**：恢复旧 Collection schema，恢复已删除文件，重新索引
