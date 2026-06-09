# 知识库系统 MVP 开发日志

## 2026-06-08

### 第一阶段：架构设计与核心模型

- [x] 编写 MVP 详细分析文档 ([KNOWLEDGE_BASE_MVP_ANALYSIS.md](KNOWLEDGE_BASE_MVP_ANALYSIS.md))，覆盖 20 个章节：背景目标、设计原则、目标架构、数据模型、解析策略、LLM 语义抽取、向量化与索引、检索流程、MVP 范围、模块划分、API 设计、Prompt 草案、火山引擎接入、风险处理、评测方案、分阶段路线图、技术选型、验收标准、最小 Demo 设计。
- [x] 实现核心数据模型 ([kb_mvp/models.py](kb_mvp/models.py))，包括：
  - `RawDocument` — 原始文档输入
  - `SourceLocation` — 来源定位信息
  - `Asset` — 多媒体/外部资源
  - `ParsedElement` — 解析后的结构元素（含子元素树）
  - `ParsedDocument` — 标准化解析结果（含嵌入文档列表）
  - `AssetRef` / `SourceRef` — 知识块中的轻量资源/来源引用
  - `KnowledgeChunk` — 可向量化的最小知识单元
  - `SearchHit` — 检索命中结果（含分数明细）

### 第二阶段：文档解析

- [x] 实现轻量 Markdown 解析器 ([kb_mvp/parser.py](kb_mvp/parser.py))，处理：
  - 标题（`#` ~ `######`）→ title 元素，自动维护标题路径
  - 段落 → paragraph 元素，收集连续非空行
  - 管道表格 → table 元素（含 table_row 子元素），保留表头和行列语义
  - 图片语法 `![alt](url)` → image 资源
  - 视频 URL（.mp4/.mov/.avi/.mkv/.webm/.m3u8）→ video 资源
  - 嵌入文档链接（.md/.txt/.html/.docx/.pdf/.xlsx/.pptx）→ 递归解析队列
  - `ParseOptions.max_depth` 控制递归深度，防止无限展开
  - 新增注释：模块 docstring、正则模式说明、常量分组、主循环三分支注释、三遍提取注释

### 第三阶段：文本处理

- [x] 实现中英文混合分词器 ([kb_mvp/text.py](kb_mvp/text.py))，支持：
  - 英文/数字连续词提取
  - 中文整段提取 + 单字 + 二字词 + 三字词（提升短口语与长文本的重合率）
  - 用作 BM25 检索和 mock 重排的基础

### 第四阶段：LLM 服务层

- [x] 定义 LLM 服务抽象接口 ([kb_mvp/llm.py](kb_mvp/llm.py))：
  - `LLMService` Protocol — `extract_chunks` / `rewrite_query` / `rerank`
  - `MockLLMService` — 确定性本地替身，用规则模拟三个 LLM 能力
- [x] `extract_chunks`：段落按 ~180 字窗口合并，表格转写自然语言陈述，自动关联资源引用和来源元数据
- [x] `rewrite_query`：少量同义表达替换（如"进库"→"进入知识库"），提取关键词
- [x] `rerank`：基于词项重合度排序，输出 `(chunk_id, score, reason)` 三元组
- [x] 正文规范化 `_normalize_sentence`：压缩空白，自动补句号

### 第五阶段：Embedding 服务层

- [x] 定义 Embedding 服务抽象接口 ([kb_mvp/embedding.py](kb_mvp/embedding.py))：
  - `EmbeddingService` Protocol — `embed_texts`
  - `HashEmbeddingService` — 确定性 hash embedding（SHA-256 → 固定维度 → L2 归一化），适合流程验证
- [x] 实现余弦相似度计算 `cosine_similarity`

### 第六阶段：混合检索索引

- [x] 实现内存版混合索引 ([kb_mvp/index.py](kb_mvp/index.py))：
  - `InMemoryHybridIndex` — 同时保存向量和 BM25 统计
  - `vector_search`：余弦相似度全量计算排序
  - `bm25_search`：标准 BM25 公式（k1=1.5, b=0.75），含 IDF 和文档长度归一化
  - `hybrid_search`：双路召回 → RRF 融合
  - `reciprocal_rank_fusion`：RRF 公式 `score = 1/(k+rank_1) + 1/(k+rank_2)`，k=60

### 第七阶段：入库与检索流水线

- [x] 实现内存版完整流水线 ([kb_mvp/pipeline.py](kb_mvp/pipeline.py))：
  - `InMemoryKnowledgeBase` — 统一入口，组合 parser + LLM + embedding + index
  - `ingest()`：BFS 队列处理文档，访问去重 + 深度限制，解析 → 语义抽取 → 向量化 → 落索引
  - `search()`：查询改写 → 向量化 → 混合召回（recall_k=20） → LLM 重排 → 取 top_k
  - `get_chunk()`：按 ID 查询单个知识块
  - 输出格式兼容分析文档中的 API 设计

### 第八阶段：端到端演示

- [x] 编写命令行 Demo ([demo.py](demo.py))，验证完整闭环：
  - 输入：一篇包含标题、段落、表格、图片、视频链接、嵌入文档链接的 Markdown
  - 递归解析 1 层嵌入文档
  - 调用 `ingest` 入库
  - 调用 `search` 检索（口语化问题："上传以后怎么知道进库成功了？"）
  - 输出 ingest 结果和 search 结果 JSON

### 模块总览

| 文件 | 职责 |
|------|------|
| [kb_mvp/__init__.py](kb_mvp/__init__.py) | 包描述 |
| [kb_mvp/models.py](kb_mvp/models.py) | 核心数据模型（9 个 dataclass） |
| [kb_mvp/parser.py](kb_mvp/parser.py) | Markdown 解析器（含递归文档发现） |
| [kb_mvp/text.py](kb_mvp/text.py) | 中英文混合分词 |
| [kb_mvp/llm.py](kb_mvp/llm.py) | LLM 接口 + Mock 实现 |
| [kb_mvp/embedding.py](kb_mvp/embedding.py) | Embedding 接口 + Hash Mock |
| [kb_mvp/index.py](kb_mvp/index.py) | 内存混合索引（向量 + BM25 + RRF） |
| [kb_mvp/pipeline.py](kb_mvp/pipeline.py) | 入库与检索流水线 |
| [demo.py](demo.py) | 端到端命令行演示 |
| [KNOWLEDGE_BASE_MVP_ANALYSIS.md](KNOWLEDGE_BASE_MVP_ANALYSIS.md) | MVP 详细分析文档（20 章） |
