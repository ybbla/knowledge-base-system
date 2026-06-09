## Context

基于 `KNOWLEDGE_BASE_ANALYSIS.md` 的设计，实现阶段 1 的完整入库与检索链路。阶段 1 的关键约束：所有存储和索引采用内存实现，不依赖 Milvus 和 MinIO，但通过接口抽象预留替换能力；数据模型和 API 字段仍按正式系统设计保留可渲染资源引用、来源追踪和检索评分明细。

## Goals / Non-Goals

**Goals:**
- Markdown/TXT 文档的结构解析（标题、段落、表格、图片/视频链接、嵌入文档链接）
- 解析层与语义层分离：解析阶段产出 Document、ParsedElement、Asset，语义阶段再决定 KnowledgeChunk 边界
- LLM 驱动的语义提取：将解析元素按结构窗口输入 LLM，生成独立知识块，并保留 `asset_refs`、`source_refs`
- 内存向量索引（numpy 余弦相似度）和 BM25 索引（基于 rank-bm25）
- 检索链路：查询重写 → 双路召回各 top 50 → RRF 融合 → LLM 重排 top 20 → 返回 top 5
- `/ingest`（异步入库）、`GET /ingest/{job_id}` 和 `/search`（同步检索）API
- 核心数据模型实现为 Pydantic models

**Non-Goals:**
- DOCX/PDF/XLSX/PPTX 解析（阶段 4）
- MinIO 对象存储（阶段 2）
- Milvus 持久化索引（阶段 3）
- 图片/视频的视觉理解（阶段 5）
- 知识类型升级（阶段 6）
- 多轮对话上下文
- 增量更新和文档版本管理
- 冲突处理

## Decisions

### 1. 内存优先，接口驱动
所有存储层（向量索引、BM25 索引、资源存储）通过抽象基类定义接口，阶段 1 提供内存实现。后续接入 Milvus/MinIO 时只需新增实现类，不修改调用方。

- `VectorIndex` (abc) → `MemoryVectorIndex`
- `BM25Index` (abc) → `MemoryBM25Index`
- `AssetStore` (abc) → `MemoryAssetStore`

### 2. 结构窗口划分策略
LLM 语义提取优先保持文档结构完整；当文档超过模型上下文、成本过高或结构复杂时，以结构窗口输入。窗口划分规则：

- 以 h2 或更高层级标题为自然边界，同一标题下的元素归入同一窗口
- 单窗口大小由 `max_window_tokens` 配置控制，阶段 1 默认 3000 token
- 超限时在段落、表格或资源边界处拆分
- 窗口间重叠标题路径和末尾 1 个关键元素，避免语义断裂
- 嵌入文档在父窗口中仅标注 `embedded_doc_id` 和标题，子文档知识块独立生成

### 3. RRF 融合（k=60）
向量检索和 BM25 检索结果使用 Reciprocal Rank Fusion 融合：

```
score = 1/(k + vector_rank) + 1/(k + bm25_rank), k=60
```

选择 RRF 而非加权归一化的原因：不依赖不同检索系统的分数分布假设，无需校准。

### 4. LLM 重排而非 Cross-encoder
阶段 1 用 LLM 做重排（将候选 chunk 列表 + 原始查询输入 LLM，输出排序结果）。原因：无需额外部署模型。缺点是 token 消耗较大（20 候选 × ~200 token ≈ 4000 token/次搜索），后续可替换为专用 reranker。

### 5. 异步入库
`POST /ingest` 立即返回 `{status: "accepted", job_id}`，后台处理解析→LLM 提取→embedding→索引写入。客户端轮询 `GET /ingest/{job_id}` 查询进度。

### 6. Embedding 输入格式
向量化输入直接使用 `KnowledgeChunk.content`。`title_path`、`knowledge_type`、文档状态、语言等字段保留在知识块或索引元数据中，用于过滤、展示、BM25 或重排，不进入 embedding 输入，避免稀释正文语义。

### 7. 递归解析限制
- 最大递归深度：3
- 已访问文档 hash 去重
- 单文档最大解析元素数：1000
- 跳过原因记录在 Document.metadata.skipped_reason
- 预留单资源最大下载大小、单任务最大处理时间和 URL 域名限制配置，阶段 1 对外部资源仅识别和关联，不强制下载处理

## Risks / Trade-offs

- [LLM 幻觉] 模型可能编造图片/视频/表格中不存在的信息 → Prompt 明确禁止编造，对无上下文资源只描述"存在一个资源"不猜内容
- [资源语义有限] 阶段 1 只识别和关联图片/视频链接，不做视觉理解或视频理解 → `Asset.extracted_text` 可为空，后续阶段异步补充后再更新知识块
- [检索质量] 向量和 BM25 各有盲区 → 双路召回 + RRF 融合 + LLM 重排三层防护
- [LLM JSON 输出不稳定] 语义提取依赖 LLM 输出严格 JSON → 做 schema 校验 + 解析失败重试（最多 3 次）
- [内存索引不可持久化] 服务重启丢失所有索引 → 阶段 1 仅为开发验证，阶段 3 迁移至 Milvus 解决
- [成本] 每次搜索调用 1 次 query rewrite + 1 次 rerank LLM 调用 → 后续可换专用模型降低成本
