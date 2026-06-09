# 知识库系统 MVP 详细分析文档

## 1. 背景与目标

本系统目标是把多格式、强混合内容的原始文档转换为可检索、可渲染、可追溯的知识块。原始文档可能包含：

- 普通文字
- 表格
- 图片
- 视频链接
- 嵌入文档链接
- 表格单元格中的文字、图片、视频链接、嵌入文档链接
- 嵌入文档内部的递归混合内容

目标不是简单做“文档切片”，而是先解析文档结构，再用大模型把内容重组为独立、语义高度集中的文本块，使每个知识块尽量满足：

- 可直接向量化
- 独立可读，不依赖原文上下文
- 语义边界清晰
- 能关联图片、视频等可渲染资源
- 能保留来源、层级、页码、标题、嵌入关系等元数据
- 当前统一按陈述型知识处理，但预留知识类型字段，便于后续扩展关系型、流程型知识

最终检索链路为：

1. 用户输入请求
2. LLM 查询重写
3. 向量检索 + BM25 检索
4. 融合召回
5. 重排
6. 返回知识块

MVP 阶段优先完成端到端闭环，所有数据先存内存；LLM 服务使用火山引擎提供的模型：

- 语言模型：Doubao-Seed-2.0-pro
- 嵌入模型：Doubao-embedding-vision

Milvus 和 MinIO 在 MVP 中先以接口和数据模型预留，后续替换内存实现。

## 2. 总体设计原则

### 2.1 文档解析与语义整理分层

系统应明确区分两件事：

- 解析层：尽可能忠实地提取文档中的结构化元素，例如段落、标题、表格、图片、视频链接、附件链接、页码、层级等。
- 语义层：由 LLM 把解析结果转换为知识块，进行表格语义化、图片内容融合、视频内容融合、跨元素上下文整理。

不要在解析阶段过早决定知识块边界。解析阶段产出的是中间结构，知识块边界应主要由语义层生成。

### 2.2 多模态资源外置，语义内容内聚

图片和视频不应直接塞入文本块，但其内容需要由 LLM 或多模态模型提取后自然融合到文本块中。

推荐知识块形态：

- `content`：可向量化的自然语言正文，包含图片/视频被理解后的语义描述。
- `assets`：与该正文相关的图片、视频、附件等资源引用。
- `render_hints`：前端渲染提示，例如图片显示位置、视频播放卡片标题等。

这样既能提升检索效果，也能在答案展示时渲染原始多媒体资源。

### 2.3 表格不保留表格形态

表格对检索通常不友好，尤其当表格单元格里还有图片、视频、嵌入文档时，直接向量化表格文本会丢失大量语义。

推荐策略：

- 解析表格结构，保留行列、表头、合并单元格、标题、上下文位置。
- 把每行、每组行、每个指标、每个实体关系转换为自然语言陈述。
- 表格中的图片、视频、嵌入文档按普通资源递归处理。
- 最终不保存原表格作为主要检索内容，但可在 `source_fragments` 中保留来源定位。

### 2.4 递归解析必须有边界

嵌入文档可能继续包含嵌入文档，因此需要递归解析。但必须设置保护：

- 最大递归深度
- 已访问文档去重
- 单文档最大解析元素数
- 单资源最大下载大小
- 单任务最大处理时间
- URL 白名单或域名限制

MVP 可先设置简单限制，例如最大递归深度为 3，最大资源大小为 100 MB。

## 3. 目标架构

```text
                         +-------------------+
                         |   User Query      |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | Query Rewriter    |
                         | Doubao LLM        |
                         +---------+---------+
                                   |
                    +--------------+--------------+
                    |                             |
                    v                             v
          +-------------------+         +-------------------+
          | Vector Retrieval  |         | BM25 Retrieval    |
          | Milvus / Memory   |         | Milvus / Memory   |
          +---------+---------+         +---------+---------+
                    |                             |
                    +--------------+--------------+
                                   |
                                   v
                         +-------------------+
                         | Hybrid Fusion     |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | Reranker / LLM    |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | Knowledge Blocks  |
                         +-------------------+
```

文档入库链路：

```text
Raw Documents
     |
     v
Document Loader
     |
     v
Structure Parser
     |
     +--> Text Elements
     +--> Table Elements
     +--> Image Elements -----> Asset Store -----> MinIO / Memory
     +--> Video Elements -----> Asset Store -----> MinIO / Memory
     +--> Embedded Docs ------> Recursive Parse
     |
     v
Normalized Document Tree
     |
     v
LLM Semantic Extractor
     |
     v
Knowledge Blocks
     |
     +--> Embedding Model
     |
     v
Hybrid Index
     |
     +--> Vector Index: Milvus / Memory
     +--> BM25 Index: Milvus / Memory
```

## 4. 核心数据模型

### 4.1 原始文档

```json
{
  "doc_id": "doc_001",
  "title": "产品使用手册",
  "source_uri": "file:///docs/manual.docx",
  "source_type": "docx",
  "created_at": "2026-06-08T10:00:00Z",
  "metadata": {
    "owner": "product-team",
    "tags": ["manual", "product"]
  }
}
```

### 4.2 解析元素

解析元素是文档解析层的标准中间格式。

```json
{
  "element_id": "el_001",
  "doc_id": "doc_001",
  "parent_element_id": null,
  "element_type": "paragraph",
  "text": "系统支持通过网页端上传知识文档。",
  "children": [],
  "assets": [],
  "source_location": {
    "page": 3,
    "section_path": ["1 产品概述", "1.2 上传文档"],
    "table_id": null,
    "row": null,
    "column": null
  },
  "metadata": {}
}
```

`element_type` 建议包括：

- `title`
- `paragraph`
- `list`
- `table`
- `table_row`
- `table_cell`
- `image`
- `video`
- `link`
- `embedded_document`
- `code`
- `unknown`

### 4.3 资源对象

图片、视频、嵌入附件等统一抽象为资源对象。

```json
{
  "asset_id": "asset_001",
  "asset_type": "image",
  "original_uri": "https://example.com/a.png",
  "storage_uri": "minio://kb-assets/doc_001/a.png",
  "mime_type": "image/png",
  "size_bytes": 123456,
  "hash": "sha256:...",
  "extracted_text": "图片展示了用户上传文档后的解析状态，包括成功、失败和处理中三种状态。",
  "metadata": {
    "width": 1200,
    "height": 800
  }
}
```

MVP 阶段可使用内存对象：

```json
{
  "asset_id": "asset_001",
  "asset_type": "image",
  "storage_uri": "memory://asset_001",
  "content_bytes": "<in-memory-bytes>",
  "extracted_text": "..."
}
```

### 4.4 知识块

知识块是向量化和检索的最小单位。

```json
{
  "chunk_id": "chunk_001",
  "doc_id": "doc_001",
  "content": "系统支持通过网页端上传知识文档。上传后，页面会展示解析状态，包括处理中、成功和失败。用户可以根据状态判断文档是否已经进入知识库。",
  "knowledge_type": "declarative",
  "assets": [
    {
      "asset_id": "asset_001",
      "asset_type": "image",
      "storage_uri": "minio://kb-assets/doc_001/upload-status.png",
      "caption": "上传状态示意图",
      "relation": "evidence"
    }
  ],
  "source_refs": [
    {
      "doc_id": "doc_001",
      "element_id": "el_002",
      "source_location": {
        "page": 3,
        "section_path": ["1 产品概述", "1.2 上传文档"]
      }
    }
  ],
  "metadata": {
    "title_path": ["产品使用手册", "上传文档"],
    "language": "zh-CN",
    "chunk_index": 1,
    "token_count": 92,
    "confidence": 0.86,
    "created_by": "Doubao-Seed-2.0-pro"
  }
}
```

`knowledge_type` 当前统一为：

- `declarative`

预留未来类型：

- `relational`
- `procedural`

### 4.5 检索结果

```json
{
  "query": "上传文档后怎么看解析成功没有？",
  "rewritten_query": "用户上传知识文档后，如何查看文档解析状态以及成功或失败结果？",
  "results": [
    {
      "chunk_id": "chunk_001",
      "content": "系统支持通过网页端上传知识文档...",
      "score": 0.92,
      "score_detail": {
        "vector_score": 0.89,
        "bm25_score": 0.73,
        "rerank_score": 0.92
      },
      "assets": [
        {
          "asset_type": "image",
          "storage_uri": "minio://kb-assets/doc_001/upload-status.png",
          "caption": "上传状态示意图"
        }
      ],
      "metadata": {
        "doc_id": "doc_001",
        "title_path": ["产品使用手册", "上传文档"]
      }
    }
  ]
}
```

## 5. 文档解析策略

### 5.1 多格式输入

建议 MVP 支持优先级：

1. Markdown / TXT
2. HTML
3. PDF
4. DOCX
5. XLSX / CSV
6. PPTX

MVP 可以先选 2 到 3 种最常见格式实现，例如 Markdown、HTML、DOCX。PDF、PPTX、XLSX 可先定义接口。

### 5.2 解析器接口

```python
class DocumentParser:
    def supports(self, source_type: str) -> bool:
        ...

    def parse(self, document: RawDocument) -> ParsedDocument:
        ...
```

解析器输出统一的 `ParsedDocument`：

```python
class ParsedDocument:
    doc_id: str
    root_elements: list[ParsedElement]
    assets: list[Asset]
    embedded_documents: list[RawDocument]
    metadata: dict
```

### 5.3 表格解析

表格需要保留结构信息，但不直接作为最终知识块。

推荐中间格式：

```json
{
  "element_type": "table",
  "table": {
    "caption": "系统状态说明",
    "headers": ["状态", "含义", "用户操作"],
    "rows": [
      {
        "cells": [
          {"text": "处理中", "assets": []},
          {"text": "系统正在解析文档", "assets": []},
          {"text": "等待完成", "assets": []}
        ]
      }
    ]
  }
}
```

LLM 处理时可生成：

```text
当文档状态为“处理中”时，表示系统正在解析文档，用户通常只需要等待处理完成。
```

如果表格中有图片：

```text
当上传状态图标显示为绿色对勾时，表示文档已经解析成功，可以进入检索流程。该说明来自状态表格中的图标和文字描述。
```

### 5.4 图片处理

最终架构：

1. 从文档或 URL 中提取图片。
2. 下载或抽取图片字节。
3. 计算 hash 去重。
4. 上传到 MinIO。
5. 调用多模态模型提取图片语义。
6. 把图片语义合并到相关文本上下文中。
7. 在知识块 `assets` 字段中关联图片链接。

MVP 阶段：

- 图片可先不真实上传 MinIO。
- 使用 `memory://asset_id` 模拟存储。
- 如果图片是远程 URL，可先保存 URL 元数据；下载逻辑可延后。
- 图片语义提取接口先保留，必要时用 LLM mock 或人工 caption。

### 5.5 视频处理

视频比图片复杂，应拆成两层：

- 资源层：下载、存储、转码、截图、音频抽取。
- 语义层：根据标题、周边文本、字幕、语音转写、关键帧描述生成视频语义。

推荐处理链路：

1. 识别视频链接。
2. 下载视频或记录外部链接。
3. 上传到 MinIO。
4. 提取字幕或语音转写。
5. 抽取关键帧。
6. 对关键帧做视觉描述。
7. LLM 汇总为自然语言。
8. 与附近文本融合成知识块。

MVP 阶段建议：

- 只识别视频链接。
- 不下载大视频。
- `Asset` 中记录 `original_uri` 和 `storage_uri`。
- 如果有标题、链接文本、周边段落，则用 LLM 生成保守描述。
- 对没有字幕或上下文的视频，不强行生成具体内容，避免幻觉。

### 5.6 嵌入文档递归解析

嵌入文档可来自：

- 文档中的超链接
- 附件
- HTML iframe
- Office 文档内嵌对象
- 表格单元格中的文档链接

递归解析策略：

```text
parse_document(doc, depth):
    if depth > max_depth:
        record_skipped_reason("max_depth_exceeded")
        return

    if doc.hash in visited:
        record_skipped_reason("duplicated_document")
        return

    parsed = parser.parse(doc)

    for embedded_doc in parsed.embedded_documents:
        parse_document(embedded_doc, depth + 1)
```

嵌入关系应进入元数据：

```json
{
  "doc_id": "doc_child_001",
  "parent_doc_id": "doc_001",
  "embed_path": ["doc_001", "el_009", "doc_child_001"],
  "depth": 1
}
```

## 6. LLM 语义抽取设计

### 6.1 输入

LLM 不应一次吃整个大文档，而应按结构窗口输入。一个结构窗口可包含：

- 当前标题路径
- 当前段落
- 相邻段落
- 表格结构化 JSON
- 图片 caption
- 视频 caption
- 来源位置
- 嵌入文档摘要

示例输入：

```json
{
  "title_path": ["用户手册", "上传知识文档"],
  "elements": [
    {
      "type": "paragraph",
      "text": "用户可以在知识库页面上传文档。"
    },
    {
      "type": "table",
      "caption": "上传状态",
      "headers": ["状态", "说明"],
      "rows": [
        ["处理中", "系统正在解析"],
        ["成功", "文档已经进入知识库"],
        ["失败", "需要查看失败原因并重新上传"]
      ]
    },
    {
      "type": "image",
      "caption": "界面截图中包含上传按钮和状态列表。",
      "asset_id": "asset_001"
    }
  ]
}
```

### 6.2 输出

LLM 应输出严格 JSON，便于程序落库。

```json
{
  "chunks": [
    {
      "content": "用户可以在知识库页面上传文档。上传后，系统会显示解析状态：处理中表示系统正在解析，成功表示文档已经进入知识库，失败表示需要查看失败原因并重新上传。",
      "knowledge_type": "declarative",
      "asset_ids": ["asset_001"],
      "source_element_ids": ["el_001", "el_002", "el_003"],
      "confidence": 0.9
    }
  ]
}
```

### 6.3 Prompt 要点

系统提示词应明确：

- 你是知识库构建助手。
- 目标是生成可独立检索的语义块。
- 不要保留表格格式，要转成自然语言陈述。
- 图片、视频内容要自然融入文本。
- 不要编造图片或视频中没有的信息。
- 每个块只表达一个高集中主题。
- 每个块必须脱离上下文可读。
- 输出必须是合法 JSON。
- 当前知识类型统一为 `declarative`。
- 如果能判断关系型或流程型，也只在 `metadata.detected_type` 标注，不改变主类型。

### 6.4 知识块粒度

建议控制：

- 中文 150 到 500 字为主。
- 一个块只覆盖一个问题或一个事实簇。
- 表格一行一个语义点时，可一行一个块。
- 表格是同一主题多个状态时，可合并为一个块。
- 图片或视频只作为证据时，不单独成块。
- 图片或视频本身承载主要知识时，可以单独成块。

## 7. 向量化与索引设计

### 7.1 Embedding 输入

对每个知识块，向量化文本建议不只包含 `content`，还应拼接少量标题路径：

```text
标题路径：用户手册 > 上传知识文档
内容：用户可以在知识库页面上传文档。上传后，系统会显示解析状态...
知识类型：declarative
```

不建议把大量元数据拼入 embedding 输入，否则会稀释正文语义。

### 7.2 Milvus 目标设计

Milvus collection 可包含：

- `chunk_id`
- `doc_id`
- `embedding`
- `content`
- `sparse_vector` 或 BM25 相关字段
- `knowledge_type`
- `title_path`
- `source_refs`
- `asset_refs`
- `metadata`

如果使用 Milvus 的稀疏向量或 BM25 能力，可在同一个系统中实现混合检索；如果能力限制不满足，也可以把 BM25 独立放到 Elasticsearch / OpenSearch。当前需求指定 Milvus，设计上先保留 Milvus hybrid search 抽象。

### 7.3 MVP 内存索引

内存版可实现两个索引：

- `InMemoryVectorIndex`：保存 chunk embedding，用余弦相似度检索。
- `InMemoryBM25Index`：用简单 BM25 实现关键字召回。

接口保持与未来 Milvus 版本一致：

```python
class ChunkIndex:
    def add_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        ...

    def vector_search(self, query_embedding: list[float], top_k: int) -> list[SearchHit]:
        ...

    def bm25_search(self, query: str, top_k: int) -> list[SearchHit]:
        ...
```

## 8. 检索流程

### 8.1 查询重写

输入用户原始问题：

```text
上传之后怎么知道成功了没？
```

LLM 重写为：

```text
用户上传知识文档后，如何查看文档解析状态，以及如何判断解析成功或失败？
```

查询重写可以同时输出：

```json
{
  "rewritten_query": "用户上传知识文档后，如何查看文档解析状态，以及如何判断解析成功或失败？",
  "keywords": ["上传", "文档", "解析状态", "成功", "失败"],
  "intent": "查询文档上传后的解析状态判断方法"
}
```

### 8.2 双路召回

向量召回适合语义相似：

- “上传之后怎么知道成功了没”
- “文档解析状态怎么看”

BM25 适合精确词匹配：

- 产品名
- 字段名
- 错误码
- 专有名词
- 表格字段

推荐流程：

1. 对重写后的 query 生成 embedding。
2. 向量检索 top 50。
3. BM25 检索 top 50。
4. 用 RRF 或加权归一化融合。
5. 取 top 20 进入重排。
6. 返回 top 5 到 top 10。

### 8.3 融合策略

MVP 可使用 Reciprocal Rank Fusion：

```text
score = 1 / (k + vector_rank) + 1 / (k + bm25_rank)
```

其中 `k` 可取 60。

优点是简单稳定，不依赖不同检索分数的归一化。

### 8.4 重排

MVP 可先用 LLM 重排：

输入：

- 用户问题
- 候选知识块列表

输出：

- 排序后的 chunk_id
- relevance_score
- reason

后续可替换为专用 reranker 模型。

LLM 重排提示应要求只基于候选块内容判断相关性，不回答用户问题。

## 9. MVP 范围

### 9.1 MVP 必做

1. 文档输入
   - 支持 Markdown / TXT。
   - 可选支持 HTML。
   - 用统一 `ParsedElement` 表示文本、表格、图片链接、视频链接、文档链接。

2. 解析
   - 提取标题、段落、简单表格。
   - 识别图片 URL。
   - 识别视频 URL。
   - 识别嵌入文档 URL。
   - 支持有限递归解析。

3. 语义块生成
   - 调用 Doubao-Seed-2.0-pro。
   - 表格转自然语言。
   - 图片/视频先以链接和周边文本生成保守描述。
   - 输出 JSON 知识块。

4. 向量化
   - 调用 Doubao-embedding-vision。
   - 保存到内存向量索引。

5. BM25
   - 实现内存 BM25。

6. 检索
   - 查询重写。
   - 向量检索。
   - BM25 检索。
   - RRF 融合。
   - LLM 重排。
   - 返回知识块和关联资源。

7. API
   - `POST /ingest`
   - `POST /search`
   - `GET /chunks/{chunk_id}`

### 9.2 MVP 暂不做

- 真实 MinIO 上传。
- 真实 Milvus 落库。
- 大规模 PDF 版面解析。
- 视频下载、转码、关键帧抽取。
- 音视频转写。
- 文档增量更新。
- 文档冲突合并。
- 权限隔离。
- 多租户。
- 复杂知识图谱关系抽取。

### 9.3 MVP 可选

- 简单 DOCX 解析。
- 简单远程图片下载。
- 简单资产本地缓存。
- 对 LLM 输出 JSON 做自动修复。
- 加一个命令行 demo。

## 10. 推荐模块划分

```text
knowledge_base_system/
  app/
    main.py
    api/
      ingest.py
      search.py
      chunks.py
    core/
      models.py
      config.py
      errors.py
    parsers/
      base.py
      markdown_parser.py
      html_parser.py
      docx_parser.py
    assets/
      base.py
      memory_store.py
      minio_store.py
    llm/
      volcengine_client.py
      prompts.py
      semantic_extractor.py
      query_rewriter.py
      reranker.py
    indexing/
      base.py
      memory_vector.py
      memory_bm25.py
      milvus_index.py
      fusion.py
    ingestion/
      pipeline.py
      recursive_loader.py
    retrieval/
      pipeline.py
    tests/
      test_markdown_ingest.py
      test_search_pipeline.py
```

## 11. API 设计

### 11.1 文档入库

```http
POST /ingest
Content-Type: application/json
```

```json
{
  "documents": [
    {
      "title": "用户手册",
      "source_type": "markdown",
      "content": "# 上传文档\n用户可以上传文档...\n\n| 状态 | 说明 |\n|---|---|\n| 成功 | 已进入知识库 |"
    }
  ],
  "options": {
    "max_depth": 3,
    "extract_assets": true
  }
}
```

响应：

```json
{
  "job_id": "job_001",
  "status": "completed",
  "doc_ids": ["doc_001"],
  "chunk_count": 8,
  "asset_count": 2,
  "warnings": []
}
```

### 11.2 检索

```http
POST /search
Content-Type: application/json
```

```json
{
  "query": "上传后怎么看解析成功没有？",
  "top_k": 5,
  "filters": {
    "knowledge_type": ["declarative"]
  }
}
```

响应：

```json
{
  "query": "上传后怎么看解析成功没有？",
  "rewritten_query": "用户上传知识文档后，如何查看文档解析状态以及成功或失败结果？",
  "results": [
    {
      "chunk_id": "chunk_001",
      "content": "用户上传文档后，系统会展示解析状态...",
      "score": 0.92,
      "assets": [],
      "metadata": {
        "doc_id": "doc_001",
        "title_path": ["用户手册", "上传文档"]
      }
    }
  ]
}
```

## 12. Prompt 草案

### 12.1 语义块生成 Prompt

```text
你是知识库构建助手。你的任务是把解析后的文档元素转换为可直接向量化的知识块。

要求：
1. 每个知识块必须独立可读，不依赖前后文。
2. 每个知识块只表达一个高度集中的主题。
3. 表格不得保留为表格，必须转写为自然语言陈述。
4. 图片、视频的语义描述需要自然融合到正文中。
5. 不要编造图片、视频、链接文档中没有的信息。
6. 当前所有知识块的 knowledge_type 都设置为 declarative。
7. 如果你判断内容更像关系型或流程型，请在 metadata.detected_type 中标注 relational 或 procedural。
8. 必须输出合法 JSON，不要输出 Markdown。

输出格式：
{
  "chunks": [
    {
      "content": "...",
      "knowledge_type": "declarative",
      "asset_ids": [],
      "source_element_ids": [],
      "metadata": {
        "detected_type": "declarative",
        "reason": "..."
      },
      "confidence": 0.0
    }
  ]
}
```

### 12.2 查询重写 Prompt

```text
你是知识库检索查询改写助手。请把用户问题改写为适合向量检索和关键词检索的查询。

要求：
1. 保留用户原意。
2. 补全省略的主语、动作和对象。
3. 提取重要关键词。
4. 不要回答问题。
5. 输出合法 JSON。

输出格式：
{
  "rewritten_query": "...",
  "keywords": ["..."],
  "intent": "..."
}
```

### 12.3 重排 Prompt

```text
你是检索结果重排助手。请根据用户问题判断候选知识块的相关性。

要求：
1. 只判断候选块是否能回答或支持回答用户问题。
2. 不要补充候选块以外的信息。
3. 返回从高到低排序的 chunk_id。
4. 输出合法 JSON。

输出格式：
{
  "ranked_results": [
    {
      "chunk_id": "...",
      "relevance_score": 0.0,
      "reason": "..."
    }
  ]
}
```

## 13. 火山引擎模型接入建议

建议封装统一客户端，不把模型厂商细节扩散到业务逻辑中。

```python
class LLMClient:
    def chat_json(self, messages: list[dict], schema: dict | None = None) -> dict:
        ...

class EmbeddingClient:
    def embed_text(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_multimodal(self, inputs: list[dict]) -> list[list[float]]:
        ...
```

配置项：

```text
VOLCENGINE_API_KEY=
VOLCENGINE_BASE_URL=
VOLCENGINE_LLM_MODEL=Doubao-Seed-2.0-pro
VOLCENGINE_EMBEDDING_MODEL=Doubao-embedding-vision
```

注意事项：

- 具体 API endpoint、鉴权方式、模型 ID 以火山引擎官方控制台和 SDK 为准。
- LLM 输出 JSON 必须做校验和重试。
- 大文档处理要限制单次请求 token 数。
- 多模态输入要区分文本 embedding、图片 embedding、图片理解三类能力，避免把 embedding 模型当作通用视觉理解模型使用。

## 14. 关键风险与处理

### 14.1 LLM 幻觉

风险：模型可能为图片、视频或表格补充不存在的信息。

处理：

- Prompt 明确禁止编造。
- 对无上下文视频只描述“存在一个视频资源”，不猜内容。
- 每个知识块保留 source refs。
- 低置信度块进入人工复核或降权。

### 14.2 表格语义丢失

风险：表格转文本时丢失行列关系。

处理：

- 解析阶段保留 headers、row、column。
- LLM 输入中提供表格 caption、表头、行数据。
- 对复杂表格按行组拆分，而不是整表一次处理。

### 14.3 递归解析爆炸

风险：嵌入文档不断递归，资源量不可控。

处理：

- 设置最大深度。
- 设置最大资源数量。
- URL 去重。
- 内容 hash 去重。
- 记录 skipped reason。

### 14.4 多媒体处理成本高

风险：视频下载、转码、转写成本大，处理慢。

处理：

- MVP 先识别和关联视频链接。
- 后续异步处理视频。
- 视频语义提取结果可二次更新知识块。

### 14.5 检索质量不稳定

风险：向量召回和 BM25 各有盲区。

处理：

- 混合召回。
- 查询重写。
- RRF 融合。
- LLM 或 reranker 重排。
- 建立评测集持续评估。

## 15. 评测方案

MVP 至少准备一组小型人工评测集：

```json
[
  {
    "query": "上传文档后如何判断解析成功？",
    "expected_chunk_ids": ["chunk_001"],
    "expected_keywords": ["上传", "解析状态", "成功"]
  }
]
```

指标：

- Recall@5
- MRR@5
- nDCG@10
- 重排后 top1 命中率
- LLM 语义块人工可读性评分
- 多媒体关联准确率

## 16. 分阶段路线图

### 阶段 1：内存版闭环

- Markdown / TXT 解析
- 简单表格解析
- 图片/视频链接识别
- LLM 生成知识块
- Embedding
- 内存向量检索
- 内存 BM25
- 查询重写
- 融合召回
- LLM 重排
- API demo

### 阶段 2：资源存储替换

- 接入 MinIO
- 图片下载和上传
- 视频链接资源化
- 资产 hash 去重
- 前端可渲染资源 URL

### 阶段 3：索引存储替换

- 接入 Milvus
- 向量索引持久化
- BM25 / sparse 检索接入
- 混合检索参数调优

### 阶段 4：多格式增强

- DOCX
- PDF
- XLSX
- PPTX
- HTML iframe / 附件解析

### 阶段 5：多模态增强

- 图片视觉理解
- 视频关键帧
- 音频转写
- 字幕解析
- 多媒体知识块二次更新

### 阶段 6：知识类型升级

- 陈述型：事实、定义、说明
- 关系型：实体关系、属性关系、包含关系
- 流程型：步骤、条件、分支、操作流程
- 针对不同知识类型使用不同 chunk schema 和检索策略

## 17. 推荐 MVP 技术选型

后端：

- Python
- FastAPI
- Pydantic

解析：

- Markdown：markdown-it-py 或 mistune
- HTML：BeautifulSoup / lxml
- DOCX：python-docx
- PDF：PyMuPDF，后续可结合版面识别
- XLSX：openpyxl

检索：

- MVP：内存余弦相似度 + rank-bm25
- 正式：Milvus hybrid search

对象存储：

- MVP：内存 asset store
- 正式：MinIO

模型：

- LLM：Doubao-Seed-2.0-pro
- Embedding：Doubao-embedding-vision

## 18. MVP 验收标准

### 入库验收

- 能输入一篇包含标题、段落、表格、图片链接、视频链接、嵌入文档链接的 Markdown。
- 能递归解析至少 1 层嵌入文档。
- 能生成多个独立知识块。
- 表格内容被转成自然语言。
- 图片和视频资源被关联到知识块。
- 每个知识块包含来源元数据。

### 检索验收

- 用户输入口语化问题后，系统能重写查询。
- 系统能同时执行向量检索和 BM25 检索。
- 系统能融合和重排结果。
- 返回结果包含 `content`、`score`、`assets`、`metadata`。

### 工程验收

- LLM、Embedding、Index、Asset Store 都有清晰接口。
- 内存实现可被 Milvus / MinIO 替换。
- 核心流程有最小测试。
- LLM 输出 JSON 有校验和失败处理。

## 19. 建议立即实现的最小 Demo

最小 Demo 可以只做如下输入：

```markdown
# 上传知识文档

用户可以在知识库页面上传文档。

| 状态 | 说明 |
| --- | --- |
| 处理中 | 系统正在解析文档 |
| 成功 | 文档已经进入知识库 |
| 失败 | 需要查看失败原因并重新上传 |

![上传状态图](https://example.com/upload-status.png)

视频说明：https://example.com/upload-demo.mp4

更多说明见：https://example.com/embedded-doc.md
```

期望生成知识块：

```text
用户可以在知识库页面上传文档。上传后，系统会展示解析状态：处理中表示系统正在解析文档，成功表示文档已经进入知识库，失败表示需要查看失败原因并重新上传。
```

检索问题：

```text
上传以后怎么知道进库成功了？
```

期望召回该知识块，并返回图片、视频关联资源。

## 20. 总结

该知识库系统的关键不是“把文档切小”，而是把复杂混合文档转换为可检索的语义知识单元。MVP 应避免一开始实现完整 MinIO、Milvus、多格式、多媒体流水线，而应先用内存版验证：

- 文档解析标准化是否合理
- LLM 生成的知识块是否独立且语义集中
- 表格语义化是否有效
- 图片、视频资源与文本块的关联方式是否适合前端渲染
- 查询重写、混合召回、重排是否能提高检索质量

当内存版闭环跑通后，再把 Asset Store 替换为 MinIO，把 Index 替换为 Milvus，把解析器扩展到 PDF、DOCX、XLSX、PPTX，并逐步增强图片和视频的真实多模态理解能力。
