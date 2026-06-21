# Design: 检索索引层重构

## Context

知识库系统当前使用 Milvus 2.5.11，但索引层未充分利用其原生能力：
- Dense 索引：IVF_FLAT + COSINE（nlist=128）
- BM25：应用层 jieba + TF-IDF 生成稀疏向量（`SPARSE_INVERTED_INDEX` + IP 度量）
- 双路融合：Milvus `hybrid_search()` + `RRFRanker`，失败时 fallback 到外部 RRF
- 检索后从 PG `chunk_store.get_batch()` 获取 chunk 详情

Milvus 2.5 已内置 Tantivy 引擎支持原生 BM25 Function（中文分析器）和 HNSW 索引。现有架构有三重冗余：BM25 在应用层重复造轮子、融合有两条路径、chunk 详情走 PG 多一次往返。

## Goals / Non-Goals

**Goals:**
- Dense 索引使用 HNSW + COSINE，查询参数 ef 可配置
- BM25 使用 Milvus 原生 `Function(FunctionType.BM25)` + `chinese` 分析器
- 两路并行 search + 应用层 `rrf_fusion()` 作为唯一融合路径
- search 时 `output_fields` 带回全部 chunk 字段，消除 PG 查询
- Milvus schema 字段精简——删冗余，加必要的 `title`、`updated_at`

**Non-Goals:**
- PG chunk 表不删除（CRUD API、列表分页、JOIN 查询仍依赖 PG）
- 入库流程不改变双写逻辑（PG + Milvus 并行写）
- API 接口签名不改变（向后兼容）

## Decisions

### 1. 外部 RRF 替代 Milvus Hybrid Search

**选择**：删除 `milvus_hybrid.py`，使用两路 `ThreadPoolExecutor` 并行 + 现有 `rrf_fusion()`。

**理由**：
- Milvus `hybrid_search()` 内部也是两个 `AnnSearchRequest`——和分别调用 search 无本质区别
- 外部 RRF 消除了一条 fallback 分支，代码更简单
- 两路 search 可独立配置参数、独立处理异常
- 延迟影响微小：并行两个请求 vs 一个 hybrid 请求，网络开销相当

### 2. Milvus 原生 BM25 替代应用层 jieba+TF-IDF

**选择**：`Function(FunctionType.BM25)` + `enable_analyzer=True` + `analyzer_params={"type": "chinese"}`。

**理由**：
- Milvus 内置 Tantivy 引擎是真正的 BM25(k1,b) 公式，比应用层 TF-IDF 近似更准确
- 中文分词由 Milvus `chinese` 分析器处理，无需应用层 jieba
- 无需维护 IDF 统计和 PG `idf_stats` 表
- 搜索时直接传原始文本，不手动编码稀疏向量

**备选方案（已拒绝）**：保留 `MilvusSparseIndex`，仅改 metric_type。拒绝理由：仍是假 BM25，且需要维护 jieba + IDF 逻辑和 PG 表。

### 3. HNSW 替代 IVF_FLAT

**选择**：HNSW + COSINE，参数 M=16, efConstruction=200, ef=64（可配置）。

**理由**：HNSW 在召回率和查询速度上均优于 IVF_FLAT，适合知识库检索的质量优先场景。参数与 Milvus 官方推荐一致。

### 4. 检索结果从 Milvus output_fields 直接获取

**选择**：search 时 `output_fields` 包含所有 chunk 字段，检索后不再走 PG。

**理由**：
- 省掉一次 PG 网络往返（search 已返回所有数据）
- 15 条 chunk 详情的数据量在 search response 中可忽略
- PG 仍保留作为 source of truth（入库、CRUD、列表查询）

### 5. Milvus Schema 设计

按 `SearchResultItem` 需求反推，与 PG `DbKnowledgeChunk` 对齐。

**删除 1 个字段**（`title_path` — 冗余，其值已在 `metadata` JSON 内），**新增 2 个字段**（`title`、`updated_at`）。

最终 Milvus schema（14 字段，当前 13 → -1 +2）：

| 字段 | 类型 | 用途 |
|------|------|------|
| `chunk_id` | VARCHAR(128) PK | 主键 |
| `doc_id` | VARCHAR(128) | 关联 + 过滤 |
| `title` | VARCHAR(512) | 结果输出 ← 新增 |
| `content` | VARCHAR(65535) + analyzer | BM25 输入 |
| `dense_vector` | FLOAT_VECTOR(1024) | 向量检索 |
| `sparse_vector` | SPARSE_FLOAT_VECTOR | BM25 检索（自动生成） |
| `category` | VARCHAR(256) | 过滤 + 输出 |
| `knowledge_type` | VARCHAR(64) | 过滤 + 输出 |
| `status` | VARCHAR(32) | 过滤 |
| `asset_refs` | VARCHAR(65535) JSON | 结果输出 |
| `source_refs` | VARCHAR(65535) JSON | 结果输出 |
| `metadata` | VARCHAR(65535) JSON | 结果输出（含 title_path） |
| `created_at` | INT64 | 过滤 + 元数据 |
| `updated_at` | INT64 | 元数据 ← 新增 |
| `asset_refs` | VARCHAR(65535) JSON | 结果输出 |
| `source_refs` | VARCHAR(65535) JSON | 结果输出 |
| `metadata` | VARCHAR(65535) JSON | 结果输出 |
| `doc_id` | VARCHAR(128) | 完整性 |
| `created_at` | INT64 | 元数据 |
| `updated_at` | INT64 | 元数据 |

> 删除了 `title_path`。其值实际存储在 `metadata` JSON 字段中（`chunk.metadata.get("title_path", [])`），无需单独列。

### 6. Bug 修复：MilvusVectorIndex 缺 upsert_fields

`documents.py` 中文档删除/恢复时调用 `vector_index.upsert_fields()`，但 `MilvusVectorIndex` 未暴露此方法（`MilvusCollectionManager` 有）。异常被 `except: pass` 静默吞掉，导致 Milvus dense 索引中的 status 未被更新。

**修复**：`MilvusVectorIndex` 和 `MilvusBM25Index` 各新增 `upsert_fields()` / `upsert_fields_batch()` 代理到 manager。`documents.py` 中移除 try-except-pass，让异常正常传播。

### 7. 新类 MilvusBM25Index

创建 `indexing/milvus_bm25.py`，实现 `BM25Index` 抽象接口。与 `MilvusVectorIndex` 共享同一 `MilvusCollectionManager` 实例。

类层次：
```
VectorIndex (ABC)          BM25Index (ABC)
    │                          │
    └─ MilvusVectorIndex       └─ MilvusBM25Index (NEW)
           │
           └─ MilvusCollectionManager (共享)
```

删除：`MilvusSparseIndex`、`MemoryBM25Index`、`milvus_hybrid.py`。

## Risks / Trade-offs

**[Risk] Schema 迁移导致短暂检索不可用**
→ **Mitigation**：Collection drop + recreate 后立即从 PG 全量重建索引（`rebuild_retrieval_indexes_from_chunks()`），通常数分钟内恢复。

**[Risk] BM25 `chinese` 分析器分词效果可能不同于 jieba**
→ **Mitigation**：部署后用评测集对比召回率，必要时调参或切换到自定义分析器（如 `lindera`）。

**[Risk] 删除 `title_path` 影响前端渲染**
→ **Mitigation**：检查前端所有 `title_path` 引用。当前仅 `SearchResultItem.metadata.title_path` 使用，从 `metadata` JSON 字段中获取即可。

**[Risk] `updated_at` 在 Milvus 中可能需要同步更新**
→ **Mitigation**：入库时同时写入 PG 和 Milvus，`upsert_fields_batch` 负责同步更新。

## Migration Plan

1. 部署新代码
2. 首次 `ensure_collection()` 检测旧 schema（无 BM25 Function）→ 自动 drop + 创建新 schema
3. `startup_resources()` 调用 `rebuild_retrieval_indexes_from_chunks()` 从 PG 全量重建
4. BM25 Function 自动对每条 `content` 生成稀疏向量

**回滚**：
1. 恢复删除的 3 个文件（`milvus_hybrid.py`、`milvus_sparse.py`、`memory_bm25.py`）
2. 恢复 `DbIdfStat` ORM 模型
3. 恢复旧版 `milvus_vector.py`（IVF_FLAT schema）
4. 重建 Collection → 重新索引

## Open Questions

- `lindera` 中文分词器是否比内置 `chinese` 更好？部署后对比评估决定
