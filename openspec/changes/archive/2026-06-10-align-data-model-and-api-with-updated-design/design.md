## Context

`KNOWLEDGE_BASE_ANALYSIS.md` 经过多轮修订，数据模型和 API 设计与已实现的阶段 1 代码存在差异。需要将现有代码对齐到最新设计，但不改变核心技术栈（Python/FastAPI/Pydantic，阶段 1 内存实现）。

当前项目结构完整，有 working 的 Markdown 解析、LLM 语义提取、内存检索链路。本 change 聚焦于模型字段和 API 接口的增量修改，不重写现有解析/检索逻辑。

## Goals / Non-Goals

**Goals:**
- 数据模型与 `KNOWLEDGE_BASE_ANALYSIS.md` §4 完全对齐
- 新增 `/upload` API，入库流程改为两步（上传 → 入库）
- `category` 贯穿全链路（Document → KnowledgeChunk → 索引 → SearchResult）
- SearchResultItem 顶层增加 `category` 和 `knowledge_type`
- 检索过滤从 `knowledge_domain` 切到 `category`
- 现有测试适配后继续通过

**Non-Goals:**
- 不引入对象存储（阶段 1 仍用本地磁盘 `/tmp/kb-uploads/`）
- 不添加校验链（魔数检测/大小限制等，文档已注明后续可加）
- 不改变 LLM Prompt（LLM 不生成 `category`，由系统继承）
- 不修改 Markdown 解析器逻辑

## Decisions

### D1: `/upload` 文件存储路径

- **决策**: 阶段 1 使用本地目录 `data/uploads/`，`source_uri` 格式为 `file://data/uploads/{uuid}.{ext}`
- **替代方案**: 直接存 MinIO（阶段 2 才引入），内存存储（大文件不可行）
- **理由**: 与现有 `data/` 目录约定一致，`file://` scheme 区分于后续 MinIO 的 `minio://`，且上传 API 的 `source_uri` 可直接传给 `/ingest`

### D2: `category` 字段默认值

- **决策**: Pydantic 模型默认 `Field(default="通用")`，Document 和 KnowledgeChunk 均设置
- **理由**: 文档 §4.1/§10.1.1 明确 "未指定则为通用"，用户上传时可选填

### D3: `category` 流转方式

- **决策**: `/upload` 接收 `category` 但仅 pass-through；`/ingest` 写入 Document；KnowledgeChunk 从 Document 继承 `category`
- **理由**: LLM 不应生成业务分类，继承保证一致且可追溯

### D4: `/ingest` 请求模型变更

- **决策**: `IngestDocument` 移除 `content` 字段（**BREAKING**），`source_uri` 改为必填。具体：

  ```python
  # Before
  class IngestDocument(BaseModel):
      title: str
      source_type: str = "markdown"
      content: str = ""
      source_uri: str | None = None

  # After
  class IngestDocument(BaseModel):
      title: str
      source_type: str
      source_uri: str
      category: str = "通用"
  ```

- **理由**: 文档 §10.1.2 要求 `source_uri` 来自 `/upload` 且不接收内联内容

### D5: 检索过滤实现

- **决策**: SearchRequest 的 filters 直接按 `category` 匹配。在 memory_vector 中，查询后遍历过滤；在 memory_bm25 中同理
- **理由**: 阶段 1 数据量小，内存后置过滤足够，无需预建分类倒排索引

### D6: SearchResultItem 结构

- **决策**: 在现有模型增加 `category` 和 `knowledge_type` 顶层字段，检索 pipeline 组装时从 KnowledgeChunk.copy
- **理由**: 文档 §4.5 和 §10.2 均要求这两个字段在顶层

## Risks / Trade-offs

- **Breaking change**: `/ingest` 不再接受内联 `content` → 影响所有现有调用方和测试。缓解：本 change 同步更新所有测试用例。
- **category 无校验**: 用户可输入任意字符串 → 缓解：文档明确说明"由用户自行定义"，后续可加枚举/校验但不阻塞阶段 1。
- **本地文件存储**: `/upload` 文件存本地 `data/uploads/` 不可横向扩展 → 缓解：阶段 2 切 MinIO 时只改 `assets/` 层实现，API 不受影响。
