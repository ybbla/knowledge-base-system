## 1. 项目初始化

- [x] 1.1 创建项目目录结构（app/api/, app/core/, parsers/, assets/, llm/, indexing/, ingestion/, retrieval/, tests/）
- [x] 1.2 创建 pyproject.toml 或 requirements.txt，添加依赖（fastapi, uvicorn, pydantic, httpx, rank-bm25, numpy, markdown-it-py）
- [x] 1.3 创建 app/core/config.py，定义配置项（VOLCENGINE_API_KEY, VOLCENGINE_BASE_URL, LLM_MODEL, EMBEDDING_MODEL, 默认 top_k 等）
- [x] 1.4 创建 app/main.py FastAPI 入口，挂载 ingest 和 search 路由

## 2. 核心数据模型

- [x] 2.1 实现 app/core/models.py：Document、ParsedElement、Asset、KnowledgeChunk、SearchResult 五个 Pydantic 模型，字段对齐 `KNOWLEDGE_BASE_ANALYSIS.md` 第 4 节
- [x] 2.2 定义 SourceLocation、AssetRef、SourceRef、Lineage、ScoreComponent 等嵌套模型
- [x] 2.3 实现 content_hash 计算工具（sha256）

## 3. LLM 客户端

- [x] 3.1 实现 llm/volcengine_client.py：LLMClient.chat_json(messages, schema?) 封装火山引擎 Chat API，支持 JSON mode 输出
- [x] 3.2 实现 EmbeddingClient.embed_text(texts) 封装火山引擎 Embedding API
- [x] 3.3 实现 JSON 校验和重试逻辑（失败最多重试 3 次）

## 4. 文档解析

- [x] 4.1 实现 parsers/base.py：DocumentParser 抽象基类（supports, parse 方法签名）
- [x] 4.2 实现 parsers/markdown_parser.py：解析 Markdown/TXT 为 ParsedElement 列表，提取标题、段落、列表、表格（含 structured_data）、图片链接、视频链接、嵌入文档链接、代码块
- [x] 4.3 解析时为每个元素生成 element_id、设置 sequence_order、填充 source_location（含 section_path, table_path, char_start/end）
- [x] 4.4 解析时创建 Asset 记录（图片/视频链接），设置 asset_type、original_uri、mime_type

## 5. 资源存储

- [x] 5.1 实现 assets/base.py：AssetStore 抽象基类（put, get, delete）
- [x] 5.2 实现 assets/memory_store.py：MemoryAssetStore，内存字典存储

## 6. 递归文档加载

- [x] 6.1 实现 ingestion/recursive_loader.py：递归解析入口，支持 max_depth、hash 去重、元素数量限制
- [x] 6.2 递归时为子文档设置 parent_doc_id、root_doc_id、embed_path，超限时记录 skipped_reason

## 7. LLM 语义提取

- [x] 7.1 实现 llm/semantic_extractor.py：窗口化 ParsedElement 列表（h2 或更高层级边界，`max_window_tokens` 配置，段落/表格/资源边界拆分，标题路径和关键元素重叠）
- [x] 7.2 编写 llm/prompts.py 语义提取 Prompt（从 `KNOWLEDGE_BASE_ANALYSIS.md` 第 11.1 节），模板化输入窗口数据
- [x] 7.3 调用 LLMClient.chat_json 生成 KnowledgeChunk 列表，填充 `content`、`title`、`knowledge_type`、`asset_refs`、`source_refs`
- [x] 7.4 校验 LLM 输出的 `asset_refs`/`source_refs`，补齐 `doc_id`、`doc_version`、`source_location` 和资源渲染信息，创建 KnowledgeChunk 记录并落存储

## 8. 向量化与索引

- [x] 8.1 实现 indexing/base.py：VectorIndex、BM25Index 抽象基类
- [x] 8.2 实现 indexing/memory_vector.py：MemoryVectorIndex（numpy 余弦相似度，add/delete/search）
- [x] 8.3 实现 indexing/memory_bm25.py：MemoryBM25Index（rank-bm25，中文分词用 jieba，add/delete/search）
- [x] 8.4 实现 embedding 生成：直接使用 `KnowledgeChunk.content` 调用 EmbeddingClient.embed_text，title_path/knowledge_type 仅作为索引元数据
- [x] 8.5 embedding 生成后写入 MemoryVectorIndex，content 文本写入 MemoryBM25Index

## 9. 入库流水线

- [x] 9.1 实现 ingestion/pipeline.py：IngestionPipeline 编排完整入库流程（解析→递归加载→语义提取→embedding→索引写入）
- [x] 9.2 实现异步入库：创建 job_id，后台执行流水线，Document status 从 pending → processing → active/failed
- [x] 9.3 实现 GET /ingest/{job_id} 查询任务进度

## 10. 查询重写

- [x] 10.1 实现 llm/query_rewriter.py：调用 LLMClient 将用户口语化查询重写为完整检索查询
- [x] 10.2 编写 llm/prompts.py 查询重写 Prompt（从 `KNOWLEDGE_BASE_ANALYSIS.md` 第 11.2 节），要求输出 rewritten_query、keywords、intent

## 11. 检索流水线

- [x] 11.1 实现 indexing/fusion.py：RRF 融合算法（k=60）
- [x] 11.2 实现 llm/reranker.py：LLM 重排，输入候选 chunk 列表 + 原始 query，输出排序后的 chunk_id + relevance_score + reason
- [x] 11.3 编写 llm/prompts.py 重排 Prompt（从 `KNOWLEDGE_BASE_ANALYSIS.md` 第 11.3 节）
- [x] 11.4 实现 retrieval/pipeline.py：编排检索流程（查询重写→向量检索 top50 + BM25 检索 top50→RRF 融合 top20→LLM 重排→返回 top5）

## 12. API 端点

- [x] 12.1 实现 app/api/ingest.py：POST /ingest 接收 `documents[]`（title、source_type、content/source_uri）和 `options`，创建 job 并返回 `{job_id, status: "accepted", doc_ids, warnings}`
- [x] 12.2 实现 app/api/search.py：POST /search 接收 query、top_k 和 filters，执行检索流水线，返回 SearchResult 格式响应

## 13. 测试

- [x] 13.1 编写 tests/test_markdown_ingest.py：端到端测试——提交一篇含标题、段落、表格、图片链接的 Markdown，验证生成的 KnowledgeChunk 内容正确
- [x] 13.2 编写 tests/test_search_pipeline.py：端到端测试——入库后执行检索，验证重写、融合、重排链路返回正确结果，并断言 `score_components`、`asset_refs`、`source_refs`、`metadata`
- [x] 13.3 编写 tests/test_models.py：验证数据模型序列化/反序列化和 content_hash 计算
