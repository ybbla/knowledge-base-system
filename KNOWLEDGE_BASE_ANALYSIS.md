# 知识库系统开发文档

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
- 知识块在生成时即按语义分类标注（陈述型/关系型/流程型），三个阶段均已预留；当前检索、重排等下游链路统一按陈述型知识处理，后续为不同知识类型启用差异化的检索策略时无需重新入库

最终检索链路为：

1. 用户输入请求
2. LLM 查询重写
3. 向量检索 + BM25 检索
4. 融合召回
5. 重排
6. 返回知识块

系统使用火山引擎提供的模型服务：

- 语言模型：Doubao-Seed-2.0-pro
- 嵌入模型：Doubao-embedding-vision

向量检索和 BM25 检索由 Milvus 承载，图片和视频等多媒体资源由 MinIO 对象存储承载。

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

这样既能提升检索效果，也能在答案展示时渲染原始多媒体资源。

### 2.3 表格不保留表格形态

表格对检索通常不友好，尤其当表格单元格里还有图片、视频、嵌入文档时，直接向量化表格文本会丢失大量语义。

推荐策略：

- 解析表格结构，保留行列、表头、合并单元格、标题、上下文位置。
- 把每行、每组行、每个指标、每个实体关系转换为自然语言陈述。
- 表格中的图片、视频、嵌入文档按普通资源递归处理。
- 最终不保存原表格作为主要检索内容，但可在 `source_refs` 中保留来源定位。

### 2.4 递归解析必须有边界

嵌入文档可能继续包含嵌入文档，因此需要递归解析。但必须设置保护：

- 最大递归深度
- 已访问文档去重
- 单文档最大解析元素数
- 单资源最大下载大小
- 单任务最大处理时间
- URL 白名单或域名限制

建议设置明确限制，例如最大递归深度为 3，最大资源大小为 100 MB。

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
          | Milvus            |         | Milvus            |
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
     +--> Image Elements -----> Asset Store -----> MinIO
     +--> Video Elements -----> Asset Store -----> MinIO
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
     +--> Vector Index: Milvus
     +--> BM25 Index: Milvus
```

## 4. 核心数据模型

核心数据模型原则：面向正式生产系统，兼顾可追溯、可扩展和可治理。模型保留核心实体，避免过度拆分，同时保证文档、解析元素、资源、知识块和检索结果之间的关系清晰：

- `Document`：原始文档及其版本信息。
- `ParsedElement`：文档解析后的结构元素，用于追溯来源。
- `Asset`：图片、视频、附件等资源对象。
- `KnowledgeChunk`：最终用于向量化和检索的知识块。
- `SearchResult`：检索返回对象。

知识块是由文档和媒体生成出来的派生产物，通过 `source_refs` 和 `asset_refs` 回溯到来源文档和媒体。

### 4.1 文档对象

文档对象描述原始文档、嵌入文档或外部链接文档。它是追踪溯源的第一层入口。

```json
{
  "doc_id": "doc_001",
  "title": "产品使用手册",
  "source_type": "docx",
  "source_uri": "file:///docs/manual.docx",
  "source_hash": "sha256:...",
  "version": 1,
  "status": "active",
  "parent_doc_id": null,
  "root_doc_id": "doc_001",
  "ingest_job_id": "job_001",
  "created_at": "2026-06-08T10:00:00Z",
  "updated_at": "2026-06-08T10:00:00Z",
  "metadata": {
    "owner": "product-team",
    "tags": ["manual", "product"]
  }
}
```

关键字段说明：

- `doc_id`：文档唯一标识。
- `source_uri`：原始来源地址，用于追溯和重新解析。
- `source_hash`：原始内容 hash，用于识别重复文档、判断内容是否变化。
- `version`：同一文档来源的版本号，后续增量更新时递增。
- `status`：文档状态，建议包括 `active`、`deleted`、`failed`。
- `parent_doc_id`：如果该文档来自嵌入文档或链接文档，记录直接父文档。
- `root_doc_id`：递归解析链路的根文档，方便按原始上传文档聚合。
- `ingest_job_id`：所属入库任务，用于排查处理过程和回放。

### 4.2 解析元素

解析元素是文档解析层的标准中间格式，用于保留原始结构和来源位置。它不是最终检索单元，但知识块必须能通过 `source_refs` 回溯到一个或多个解析元素。

```json
{
  "element_id": "el_001",
  "doc_id": "doc_001",
  "doc_version": 1,
  "parent_element_id": null,
  "sequence_order": 1,
  "element_type": "paragraph",
  "text": "系统支持通过网页端上传知识文档。",
  "structured_data": null,
  "asset_ids": [],
  "embedded_doc_id": null,
  "source_location": {
    "page": 3,
    "section_path": ["1 产品概述", "1.2 上传文档"],
    "table_path": [],
    "char_start": 120,
    "char_end": 138
  },
  "metadata": {}
}
```

`element_type` 建议包括：

- `title` — 标题，用于构建标题路径和窗口切分
- `paragraph` — 段落，最常见的文本载体
- `list` — 列表容器，子元素通过 `parent_element_id` 归属
- `table` — 表格，结构数据存在 `structured_data` 中
- `image` — 图片资源标记
- `video` — 视频资源标记
- `embedded_document` — 嵌入文档，触发递归解析
- `code` — 代码块，原样保留不语义化改写
- `unknown` — 兜底，解析器无法识别时使用

关键字段说明：

- `text`：元素的主体文本内容，LLM 语义提取的主要消费对象。
- `element_type`：告诉 LLM 如何处理该元素——表格需展开 `structured_data`，图片需查关联资源描述，代码需原样保留。
- `doc_version`：元素来自哪个文档版本，避免后续文档更新后来源混乱。
- `parent_element_id`：保留层级关系，例如列表项属于列表容器，表格内容归于表格。
- `sequence_order`：元素在文档中的顺序号，用于重建文档流和 LLM 上下文排序。
- `structured_data`：当 `element_type` 为 `table` 时，存放 `{headers, rows}` 结构；其他类型为 null。
- `asset_ids`：当前元素直接包含或引用的资源 ID。
- `embedded_doc_id`：当 `element_type` 为 `embedded_document` 时，指向被嵌入文档的 doc_id；其他类型为 null。
- `source_location`：页码、标题路径、字符范围等定位信息，用于检索结果展示时的来源标注。

### 4.3 资源对象与内容关联

图片、视频、嵌入附件等统一抽象为资源对象。资源对象本身只负责描述“资源是什么、存在哪里、模型从资源中理解到了什么”，不直接代表知识内容。

资源与知识内容的关联发生在知识块中：知识块通过 `asset_refs` 引用资源对象，并说明该资源与当前文本块的关系、关联到哪段语义、如何渲染。

```json
{
  "asset_id": "asset_001",
  "doc_id": "doc_001",
  "source_element_id": "el_003",
  "asset_type": "image",
  "original_uri": "https://example.com/a.png",
  "storage_uri": "minio://kb-assets/doc_001/a.png",
  "content_hash": "sha256:...",
  "created_at": "2026-06-08T10:00:00Z",
  "updated_at": "2026-06-08T10:00:00Z",
  "status": "ready",
  "extracted_text": "图片展示了用户上传文档后的解析状态，包括成功、失败和处理中三种状态。",
  "error_message": null,
  "metadata": {
    "width": 1200,
    "height": 800
  }
}
```

关键字段说明：

- `asset_type`：资源类型（`image` / `video` / `audio` / `attachment`），决定后续处理链路。
- `original_uri`：资源的原始来源地址，用于追溯和重新下载。
- `storage_uri`：资源转存后的 MinIO 地址；外部不可下载资源可为 null，并通过 `status`、`error_message`。
- `content_hash`：资源内容 hash，用于去重——同一图片出现在多个文档中靠 hash 识别。
- `doc_id`：资源来自哪个文档，溯源第一跳。
- `source_element_id`：资源在解析元素中的精确位置，同一文档多处引用同一资源时靠它区分。
- `created_at` / `updated_at`：资源创建和更新时间。
- `status`：资源处理状态，包括 `pending`、`ready`、`failed`、`skipped`。
- `extracted_text`：模型对图片、视频或附件内容的理解结果，用于 LLM 语义提取时融入知识块正文。
- `error_message`：资源处理失败时的错误信息，status 为 failed 时写入。
- `metadata`：扩展字段，可存放图片宽高、视频时长、文件大小、媒体编码、外部资源访问策略等信息。

### 4.4 知识块

知识块是向量化和检索的最小单位。字段设计同时支持检索、渲染和追踪溯源。

```json
{
  "chunk_id": "chunk_001",
  "doc_id": "doc_001",
  "doc_version": 1,
  "title": "上传文档解析状态判断",
  "content": "系统支持通过网页端上传知识文档。上传后，页面会展示解析状态，包括处理中、成功和失败。用户可以根据状态判断文档是否已经进入知识库。界面截图展示了上传状态列表。",
  "content_hash": "sha256:...",
  "knowledge_type": "declarative",
  "status": "active",
  "asset_refs": [
    {
      "asset_id": "asset_001",
      "relation": "evidence",
      "linked_text": "界面截图展示了上传状态列表",
      "caption": "上传状态列表截图",
      "render": {
        "mode": "inline",
        "position": "after_linked_text"
      }
    }
  ],
  "source_refs": [
    {
      "doc_id": "doc_001",
      "doc_version": 1,
      "element_id": "el_002",
      "source_location": {
        "page": 3,
        "section_path": ["1 产品概述", "1.2 上传文档"]
      }
    }
  ],
  "ingest_job_id": "job_001",
  "metadata": {
    "title_path": ["产品使用手册", "上传文档"],
    "language": "zh-CN"
  }
}
```

关键字段说明：

- `doc_id`：知识块主要内容来源的文档。当 `source_refs` 跨文档时，此字段指向主文档。
- `doc_version`：生成该块时的文档版本。
- `title`：知识块的短标题，用于检索结果展示，与 `content` 首句的区别是 title 可包含概括性措辞。
- `content`：可直接向量化的自然语言正文，图片和视频语义应自然融合进去。
- `content_hash`：知识块正文 hash，用于重复块识别和变更检测。
- `knowledge_type`：知识块的语义类型，LLM 在生成时即按内容分类标注。当前下游检索链路统一按陈述型处理，后续为不同类型启用差异化策略时无需重新生成知识块：
  - `declarative`（陈述型）：事实、定义、属性说明、概念解释等陈述性知识。
  - `relational`（关系型）：实体之间的关联、依赖、包含、对比等关系性知识。
  - `procedural`（流程型）：步骤、操作顺序、条件分支、决策流程等过程性知识。
- `status`：知识块状态，建议包括 `active`、`superseded`、`deleted`。
- `asset_refs`：知识块与资源的关联，不只保存链接，还说明关系和渲染方式。
- `source_refs`：知识块来源，可引用多个解析元素，保证可追溯。
- `ingest_job_id`：所属入库任务，用于排查处理过程。

`asset_refs.relation` 建议包括：

- `evidence`：资源是当前文本陈述的证据或截图。
- `illustration`：资源用于辅助说明文本内容。
- `demonstration`：资源演示操作过程，常用于视频。
- `source`：资源是该知识块的主要来源。
- `attachment`：资源与知识块相关，但不直接参与语义表达。

### 4.5 检索结果

检索结果不需要保存全部字段，只返回回答、渲染和调试所需的信息。

```json
{
  "search_id": "search_001",
  "query": "上传文档后怎么看解析成功没有？",
  "rewritten_query": "用户上传知识文档后，如何查看文档解析状态以及成功或失败结果？",
  "total_count": 12,
  "results": [
    {
      "chunk_id": "chunk_001",
      "title": "上传文档解析状态判断",
      "content": "系统支持通过网页端上传知识文档...",
      "score": 0.92,
      "score_components": {
        "vector": 0.89,
        "bm25": 0.73,
        "rerank": 0.92
      },
      "asset_refs": [
        {
          "asset_id": "asset_001",
          "relation": "evidence",
          "storage_uri": "minio://kb-assets/doc_001/upload-status.png",
          "linked_text": "界面截图展示了上传状态列表",
          "caption": "上传状态列表截图",
          "render": {
            "mode": "inline",
            "position": "after_linked_text"
          }
        }
      ],
      "source_refs": [
        {
          "doc_id": "doc_001",
          "doc_version": 1,
          "element_id": "el_002",
          "source_location": {
            "page": 3,
            "section_path": ["1 产品概述", "1.2 上传文档"]
          }
        }
      ],
      "metadata": {
        "title_path": ["产品使用手册", "上传文档"],
        "knowledge_type": "declarative"
      }
    }
  ]
}
```

关键字段说明：

- `search_id`：检索请求唯一标识，用于日志关联和问题排查。
- `total_count`：符合过滤条件的知识块总数，用于前端分页。
- `score`：融合后最终分数，按此降序排列。
- `score_components`：各检索通道的独立分数，key 为通道名（vector / bm25 / rerank 等），便于调参和问题定位。
- `asset_refs`：已 resolve 的资源引用。在 KnowledgeChunk 的 `asset_refs` 基础上补充 `storage_uri`（从 Asset 解析的可渲染地址），同时保留 `linked_text`（关联到 content 中具体段落）和 `render`（渲染意图）。

## 5. 文档解析策略

### 5.1 多格式输入

建议按以下优先级支持文档格式：

1. Markdown / TXT
2. HTML
3. PDF
4. DOCX
5. XLSX / CSV
6. PPTX

开发初期可以先实现 2 到 3 种最常见格式，例如 Markdown、HTML、DOCX。PDF、PPTX、XLSX 可先定义接口并逐步补齐解析能力。

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

表格需要保留结构信息，但不直接作为最终知识块。解析器将表格结构存入 `ParsedElement.structured_data`。

推荐中间格式（即 `structured_data` 的内容）：

```json
{
  "element_type": "table",
  "table": {
    "caption": "系统状态说明",
    "headers": ["状态", "含义", "用户操作"],
    "rows": [
      {
        "cells": [
          {"text": "处理中", "asset_ids": []},
          {"text": "系统正在解析文档", "asset_ids": []},
          {"text": "等待完成", "asset_ids": []}
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
7. 在知识块 `asset_refs` 字段中关联图片链接，并说明图片与正文的关系、关联文本和渲染方式。

工程要求：

- 图片应上传 MinIO，并生成可授权访问的对象存储 URI。
- 图片资源应计算 hash，用于去重和追踪。
- 远程图片需要下载、校验大小和类型，再进入对象存储。
- 图片语义提取应通过多模态模型或图片理解服务完成，结果写入资源元数据并关联知识块。

### 5.5 视频处理

视频处理仍拆成两层，但语义层不需要把字幕、转写、关键帧拆成必选流水线：

- 资源层：识别视频链接，创建 `Asset`，记录 `original_uri`；可下载的视频上传到 MinIO 并记录 `storage_uri`。
- 语义层：优先交给多模态模型或具备视频理解能力的 LLM 直接处理，生成视频内容总结、关键主题和可检索文本。

推荐处理链路：

1. 识别视频链接。
2. 创建视频 `Asset`。
3. 可下载的视频上传到 MinIO；不可下载的视频保留外部链接。
4. 调用多模态模型或视频理解模型生成 `extracted_text`。
5. 将视频语义与标题、周边文本融合。
6. 生成或更新知识块 `content`。
7. 在知识块 `asset_refs` 中关联视频资源。

工程要求：

- 视频链接需要资源化并写入 `Asset`。
- 可下载的视频应进入 MinIO，并记录 `original_uri` 和 `storage_uri`。
- 视频语义总结优先由多模态模型直接生成，并写入 `Asset.extracted_text`。
- 字幕、语音转写和关键帧描述是可选增强手段，不作为 MVP 的必选链路。
- 对模型无法读取、证据不足或只有链接的视频，不应强行生成具体内容，避免幻觉。

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
  "embed_path": ["doc_001", "doc_child_001"],
  "depth": 1
}
```

## 6. LLM 语义抽取设计

### 6.1 输入

LLM 输入应优先保持文档结构完整。现代大上下文模型可以接受较长文档时，可直接输入整篇文档的解析结果；只有当文档超过模型上下文、成本过高或结构过于复杂时，才按结构窗口拆分。

窗口划分策略：以 h2 或更高层级标题为自然边界，相邻同标题下的元素归入同一窗口。窗口大小不设固定小上限，而应根据所选模型上下文、成本预算和输出稳定性配置，例如为 `max_window_tokens` 设置工程参数。超出限制时在段落、表格或资源边界处拆分，窗口间可重叠标题路径和最后一个关键元素，以避免语义断裂。

一个结构窗口可包含：

- 当前标题路径
- 当前段落
- 相邻段落
- 表格结构化 JSON
- 图片 caption
- 视频 caption
- 来源位置
- 嵌入文档引用（仅标注 `embedded_doc_id` 和标题，不展开内容——子文档的知识块已独立存在，检索时可跨文档召回）

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
      "title": "上传文档解析状态说明",
      "content": "用户可以在知识库页面上传文档。上传后，系统会显示解析状态：处理中表示系统正在解析，成功表示文档已经进入知识库，失败表示需要查看失败原因并重新上传。",
      "knowledge_type": "declarative",
      "asset_refs": [
        {
          "asset_id": "asset_001",
          "relation": "evidence",
          "linked_text": "系统会显示解析状态",
          "caption": "界面截图中包含上传按钮和状态列表",
          "render": {
            "mode": "inline",
            "position": "after_linked_text"
          }
        }
      ],
      "source_refs": [
        {
          "element_id": "el_001"
        },
        {
          "element_id": "el_002"
        },
        {
          "element_id": "el_003"
        }
      ]
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
- 输出字段应能映射为 `KnowledgeChunk`，至少包含 `title`、`content`、`knowledge_type`、`asset_refs`、`source_refs`。
- 输出必须是合法 JSON。
- 知识块按语义性质分为三类（`declarative` 陈述型 / `relational` 关系型 / `procedural` 流程型），LLM 在生成时即对每个块进行分类标注；当前下游检索链路对所有类型统一按陈述型处理，后续差异化策略启用时已有类型标注的基础。

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

对每个知识块，向量化文本直接使用 `KnowledgeChunk.content`。`content` 已由语义层整理为独立可读、语义集中的自然语言正文，不需要额外拼接标题路径或其他元数据。

```text
用户可以在知识库页面上传文档。上传后，系统会显示解析状态...
```

`title_path`、`knowledge_type`、文档状态、语言等字段保留在知识块或索引元数据中，用于过滤、展示、BM25 或重排，不进入 embedding 输入，避免稀释正文语义。

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

融合策略可使用 Reciprocal Rank Fusion：

```text
score = 1 / (k + vector_rank) + 1 / (k + bm25_rank)
```

其中 `k` 可取 60。

优点是简单稳定，不依赖不同检索分数的归一化。

### 8.4 重排

可先使用 LLM 重排：

输入：

- 用户问题
- 候选知识块列表

输出：

- 排序后的 chunk_id
- relevance_score
- reason

后续可替换为专用 reranker 模型。

LLM 重排提示应要求只基于候选块内容判断相关性，不回答用户问题。

> 当前检索为单轮设计。多轮对话场景下，查询重写应携带历史对话摘要，后续阶段可扩展。

## 9. 推荐模块划分

```text
knowledge_base_system/
  app/
    main.py
    api/
      ingest.py
      search.py
      chunks.py       # 知识块查询、状态更新等管理接口
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

## 10. API 设计

### 10.1 文档入库

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
    },
    {
      "title": "常见问题",
      "source_type": "html",
      "content": "<h1>常见问题</h1><p>用户可以在知识库页面查看文档解析状态。</p>"
    },
    {
      "title": "产品说明书",
      "source_type": "docx",
      "source_uri": "minio://kb-input/manual.docx"
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
  "status": "accepted",
  "doc_ids": ["doc_001", "doc_002", "doc_003"],
  "warnings": []
}
```

> 入库支持一次提交多个文档，且不同文档可以使用不同 `source_type`。系统会为每个文档创建独立的 Document 记录，并根据 `source_type` 选择对应解析器。入库为异步处理：API 收到请求后将文档内容或来源地址写入对象存储并生成 `source_uri`，创建 Document 记录（`status=pending`），投递入库任务后立即返回 `accepted`。客户端可通过 `GET /ingest/{job_id}` 查询整体进度和每个文档的处理状态。`options.extract_assets` 控制是否下载并处理图片、视频等资源，阶段 1 可设为 `false`（仅识别链接）。

### 10.2 检索

```http
POST /search
Content-Type: application/json
```

```json
{
  "query": "上传后怎么看解析成功没有？",
  "top_k": 5,
  "filters": {
    "knowledge_type": ["declarative"],
    "knowledge_domain": ["用户手册", "产品使用"]
  }
}
```

`filters.knowledge_domain` 用于按知识领域过滤检索范围，例如用户手册、产品使用、售后支持、内部制度等。知识领域可来自文档入库时的元数据，也可在语义抽取或人工管理阶段写入知识块 `metadata`。

响应：

```json
{
  "search_id": "search_001",
  "query": "上传后怎么看解析成功没有？",
  "rewritten_query": "用户上传知识文档后，如何查看文档解析状态以及成功或失败结果？",
  "total_count": 1,
  "results": [
    {
      "chunk_id": "chunk_001",
      "title": "上传文档解析状态判断",
      "content": "用户上传文档后，系统会展示解析状态...",
      "score": 0.92,
      "score_components": {
        "vector": 0.89,
        "bm25": 0.73,
        "rerank": 0.92
      },
      "asset_refs": [],
      "source_refs": [
        {
          "doc_id": "doc_001",
          "doc_version": 1,
          "element_id": "el_002",
          "source_location": {
            "page": 3,
            "section_path": ["1 产品概述", "1.2 上传文档"]
          }
        }
      ],
      "metadata": {
        "title_path": ["用户手册", "上传文档"],
        "knowledge_type": "declarative"
      }
    }
  ]
}
```

## 11. Prompt 草案

### 11.1 语义块生成 Prompt

```text
你是知识库构建助手。你的任务是把解析后的文档元素转换为可直接向量化的知识块。

知识块按语义性质分为三类，你需要根据每个块的内容特征判断其归属，通过 knowledge_type 字段标明：
- "declarative"（陈述型）：事实陈述、定义说明、属性描述、概念解释。
- "relational"（关系型）：实体之间的关联、依赖、包含、对比、层级等关系。
- "procedural"（流程型）：操作步骤、执行顺序、条件分支、决策流程。

注意：当前阶段后续检索链路对所有类型按陈述型知识统一处理，但标注正确的 knowledge_type 有助于后续升级时无需重新生成知识块。

要求：
1. 每个知识块必须独立可读，不依赖前后文。
2. 每个知识块只表达一个高度集中的主题。
3. 表格不得保留为表格，必须转写为自然语言陈述。
4. 图片、视频的语义描述需要自然融合到正文中。
5. 不要编造图片、视频、链接文档中没有的信息。
6. 必须输出合法 JSON，不要输出 Markdown。

输出格式：
{
  "chunks": [
    {
      "title": "...",
      "content": "...",
      "knowledge_type": "declarative",
      "asset_refs": [
        {
          "asset_id": "...",
          "relation": "evidence | illustration | demonstration | source | attachment",
          "linked_text": "...",
          "caption": "...",
          "render": {
            "mode": "inline",
            "position": "after_linked_text"
          }
        }
      ],
      "source_refs": [
        {
          "element_id": "..."
        }
      ]
    }
  ]
}
```

### 11.2 查询重写 Prompt

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

### 11.3 重排 Prompt

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

## 12. 火山引擎模型接入建议

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

## 13. 关键风险与处理

### 13.1 LLM 幻觉

风险：模型可能为图片、视频或表格补充不存在的信息。

处理：

- Prompt 明确禁止编造。
- 对无上下文视频只描述“存在一个视频资源”，不猜内容。
- 每个知识块保留 source refs。
- 低置信度块进入人工复核或降权。

### 13.2 表格语义丢失

风险：表格转文本时丢失行列关系。

处理：

- 解析阶段保留 headers、row、column。
- LLM 输入中提供表格 caption、表头、行数据。
- 对复杂表格按行组拆分，而不是整表一次处理。

### 13.3 递归解析爆炸

风险：嵌入文档不断递归，资源量不可控。

处理：

- 设置最大深度。
- 设置最大资源数量。
- URL 去重。
- 内容 hash 去重。
- 记录 skipped reason。

### 13.4 多媒体处理成本高

风险：视频下载、转码、转写成本大，处理慢。

处理：

- 先识别和关联视频链接。
- 后续异步处理视频。
- 视频语义提取结果可二次更新知识块。

### 13.5 检索质量不稳定

风险：向量召回和 BM25 各有盲区。

处理：

- 混合召回。
- 查询重写。
- RRF 融合。
- LLM 或 reranker 重排。
- 建立评测集持续评估。

## 14. 评测方案

至少准备一组小型人工评测集：

```json
[
  {
    "query": "上传文档后如何判断解析成功？",
    "expected_doc_id": "doc_001",
    "expected_content_contains": ["上传文档", "解析状态", "成功"],
    "min_relevant_chunks": 1
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

## 15. 分阶段路线图

### 阶段 1：基础入库与检索链路（内存实现）

- Markdown / TXT 解析
- 简单表格解析
- 图片/视频链接识别
- LLM 生成知识块
- Embedding
- 向量检索（内存）
- BM25 检索（内存）
- 查询重写
- 融合召回
- LLM 重排

### 阶段 2：资源存储

- 接入 MinIO
- 图片下载和上传
- 视频链接资源化
- 资产 hash 去重
- 前端可渲染资源 URL

### 阶段 3：索引持久化

- 接入 Milvus
- 向量索引迁移至 Milvus
- BM25 迁移至 Milvus / Elasticsearch
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

三大知识类型已在数据模型和 LLM Prompt 中完整定义，LLM 在生成知识块时即根据内容特征进行分类标注：

| knowledge_type | 中文名称 | 定义 | 示例 |
|---------------|---------|------|------|
| `declarative` | 陈述型 | 事实、定义、属性说明、概念解释 | "系统支持 Markdown 和 TXT 两种格式" |
| `relational` | 关系型 | 实体关联、依赖、包含、对比 | "订单关联用户和商品两个实体" |
| `procedural` | 流程型 | 步骤、操作顺序、条件分支、决策流程 | "退款流程：1.申请 2.审核 3.退款到账" |

已完成：
- LLM 已按内容自动分类标注 knowledge_type，字段贯穿全链路（生成 → 落库 → 索引 → 检索结果）

待完成：
- 检索时按 knowledge_type 过滤和加权，为不同知识类型启用差异化的检索策略
- 针对不同知识类型使用不同的 Prompt 策略和 chunk schema

## 16. 推荐技术选型

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

- Milvus hybrid search

对象存储：

- MinIO

模型：

- LLM：Doubao-Seed-2.0-pro（文本生成、查询重写、重排、表格语义化）
- Embedding：Doubao-embedding-vision（文本和图片向量化）
- Vision：Doubao-Seed-2.0-pro 多模态能力 或 专用视觉理解模型（图片描述、关键帧分析，阶段 5 启用）

## 17. 验收标准

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
- 返回结果包含 `content`、`score`、`score_components`、`asset_refs`、`source_refs`、`metadata`。

### 工程验收

- LLM、Embedding、Index、Asset Store 都有清晰接口。
- Milvus 和 MinIO 接入边界清晰，便于后续扩展存储、索引和资源处理能力。
- 核心流程有最小测试。
- LLM 输出 JSON 有校验和失败处理。

## 18. 总结

该知识库系统的关键不是“把文档切小”，而是把复杂混合文档转换为可检索、可渲染、可追溯的语义知识单元。开发过程中应重点验证：

- 文档解析标准化是否合理
- LLM 生成的知识块是否独立且语义集中
- 表格语义化是否有效
- 图片、视频资源与文本块的关联方式是否适合前端渲染
- 查询重写、混合召回、重排是否能提高检索质量

后续应围绕 Milvus、MinIO、多格式解析、图片理解、视频语义提取和知识类型升级持续完善工程能力。
