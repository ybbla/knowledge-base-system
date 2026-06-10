## Why

`KNOWLEDGE_BASE_ANALYSIS.md` 经过全面修订，新增了 `category` 业务分类字段、`/upload` 文件上传 API、两步入库流程（上传→入库）、以及 `knowledge_type` 在检索结果中提升为顶层字段等变更。现有代码基于旧版文档实现，数据模型和 API 均需对齐以保持一致性。

## What Changes

- 新增 `/upload` 端点：multipart/form-data 文件上传，写入本地存储并返回 `source_uri`
- **BREAKING**：`/ingest` 不再接受内联 `content` 字段，`source_uri` 改为必填（来自 `/upload`）
- Document、KnowledgeChunk、SearchResultItem 模型新增 `category` 字段（string，默认 `"通用"`）
- SearchResultItem 模型新增 `knowledge_type` 顶层字段，从 `metadata` 中移除
- 检索请求 `filters` 移除 `knowledge_domain`，改为 `filters.category`
- 内存向量/BM25 索引新增 `category` 作为可过滤字段

## Capabilities

### New Capabilities

- `file-upload`: 文件上传——multipart/form-data 接收本地文件，写入本地存储，返回 `source_uri` 和 `source_hash`

### Modified Capabilities

- `document-ingestion`: Document 模型新增 `category`；`/ingest` 请求模型移除 `content`，`source_uri` 改为必填；响应码改为 202
- `semantic-extraction`: KnowledgeChunk 模型新增 `category`，从 Document 继承
- `embedding-indexing`: 索引新增 `category` 作为可过滤元数据字段
- `hybrid-retrieval`: 检索过滤改为 `filters.category`；SearchResultItem 新增 `category` 和 `knowledge_type` 顶层字段

## Impact

- 数据模型：`app/core/models.py` — Document、KnowledgeChunk、SearchResultItem 结构变更
- API：`app/api/ingest.py` 变更；新增 `app/api/upload.py`
- 索引：`indexing/memory_vector.py`、`indexing/memory_bm25.py` 增加 category 过滤
- 检索：`app/api/search.py`、`retrieval/pipeline.py` 过滤和响应结构调整
- 无新外部依赖（阶段 1 仍全部内存/本地盘实现）
