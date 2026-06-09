## Why

知识库系统需要将混合格式的原始文档（文字、表格、图片、视频链接、嵌入文档）转换为可检索、可渲染、可追溯的语义知识块。当前设计以 `KNOWLEDGE_BASE_ANALYSIS.md` 为准，需要按阶段 1 路线图落地实现：打通"文档入库 → 结构解析 → LLM 语义提取 → 双路索引 → 混合检索 → 重排"的完整链路，同时保留后续接入 MinIO 和 Milvus 的接口边界。

## What Changes

- 新建 Python/FastAPI 项目骨架，包含 models、parsers、llm、indexing、ingestion、retrieval 模块
- 实现 Markdown/TXT 文档解析器，提取标题、段落、表格、图片/视频链接、嵌入文档链接等结构化元素，并创建 Document、ParsedElement、Asset 中间对象
- 实现 LLM 语义提取器，将解析元素按结构窗口输入 LLM，生成独立可读的 KnowledgeChunk，保留 `asset_refs` 和 `source_refs`
- 实现内存向量索引和 BM25 索引（阶段 1 不依赖 Milvus）
- 实现检索链路：查询重写 → 双路召回 → RRF 融合 → LLM 重排 → 返回结果
- 提供 `/ingest`、`GET /ingest/{job_id}` 和 `/search` API，检索结果包含 `score_components`、`asset_refs`、`source_refs`、`metadata`

## Capabilities

### New Capabilities

- `document-ingestion`: 文档入库——接收 Markdown/TXT 文档，解析为结构化元素，递归处理嵌入文档
- `semantic-extraction`: LLM 语义提取——将 ParsedElement 窗口输入 LLM，生成 KnowledgeChunk，融合表格语义和资源引用，输出 `asset_refs`/`source_refs`
- `embedding-indexing`: 向量化与索引——生成 embedding，维护内存向量索引和 BM25 索引，支持增删
- `hybrid-retrieval`: 混合检索——查询重写、双路召回（向量+BM25）、RRF 融合、LLM 重排、返回 SearchResult

### Modified Capabilities

<!-- No existing capabilities to modify -->

## Impact

- 新项目：`knowledge_base_system/` 目录，Python + FastAPI + Pydantic
- 依赖：火山引擎 API（Doubao-Seed-2.0-pro LLM、Doubao-embedding-vision Embedding）
- 数据模型：Document、ParsedElement、Asset、KnowledgeChunk、SearchResult（Pydantic models），KnowledgeChunk 通过 `asset_refs` 和 `source_refs` 回溯资源与来源
- API：`POST /ingest`、`GET /ingest/{job_id}`、`POST /search`
- 无外部存储依赖（阶段 1 全部内存实现）
