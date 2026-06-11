## Context

阶段 1 完成了完整的 Markdown→KnowledgeChunk→SearchResult 内存链路，所有状态存于进程内存。阶段 2 需要在不破坏现有链路的前提下，引入 PostgreSQL 持久化和 DOCX 解析能力。

**约束：**
- 26 个现有测试必须保持通过
- 默认行为不变（`BACKEND=memory` 时完全兼容阶段 1）
- PostgreSQL 由 docker-compose 提供，应用通过环境变量连接
- 火山引擎 API 为唯一的 LLM/Embedding 服务

## Goals / Non-Goals

**Goals:**
- 四个核心实体（Document / ParsedElement / Asset / KnowledgeChunk）的元数据持久化到 PostgreSQL
- 服务重启后数据完整保留，索引可从 PG 重建
- DOCX 文档解析为统一的 ParseResult，与 Markdown 链路无缝衔接
- 解析器按 source_type 自动选择，增加新格式只需注册
- 内存模式作为开发默认值，零依赖即可运行
- 评测集可自动化运行，输出 Recall@5 和 MRR

**Non-Goals:**
- 向量和 BM25 索引持久化（阶段 3：Milvus）
- MinIO 对象存储接入（阶段 3）
- PDF / HTML / XLSX / PPTX 解析（阶段 4）
- 多模态图片/视频语义理解（阶段 5）
- pgvector 做向量检索（仅用于元数据存储，向量继续用内存）
- Alembic 数据库迁移（阶段 2 表结构简单，直接用 `CREATE TABLE` 或 `Base.metadata.create_all`；迁移工具在表结构稳定后引入）

## Decisions

### 1. DB 层：独立 SQLAlchemy 模型 + Repository 模式

**选择**：在 `app/db/models.py` 中定义独立的 SQLAlchemy Table 映射，在 `app/db/repositories/` 中实现 Repository 类封装 CRUD，Repository 负责 Pydantic ↔ SQLAlchemy 转换。

**备选方案**：
- *SQLModel*：减少重复但耦合了 API schema 和 DB schema。阶段 2 字段已经稳定，但后续阶段 3-6 的 Milvus/MinIO 接入可能改变数据流，此时 API 层和 DB 层的解耦更有价值。
- *直接裸写 SQL*：灵活但会散落 SQL 字符串，不利于后续迁移工具引入。

**结构**：
```text
app/db/
  engine.py          # create_engine + sessionmaker
  session.py         # get_db FastAPI dependency (yield Session)
  models.py          # SQLAlchemy ORM classes
  repositories/
    base.py          # BaseRepository ABC
    documents.py     # DocumentRepository
    elements.py      # ParsedElementRepository
    chunks.py        # KnowledgeChunkRepository
    assets.py        # AssetRepository
```

Pydantic → SQLAlchemy 转换在 Repository 的 `create()` / `update()` 中完成，SQLAlchemy → Pydantic 在 `get()` / `list()` 的返回值中完成。

### 2. 后端切换：环境变量 + 工厂模式

**选择**：`config.py` 新增 `BACKEND` 字段（`memory` | `postgres`），`deps.py` 在模块加载时根据该值创建对应的实现实例。

```python
# config.py 新增
backend: str = "memory"           # "memory" | "postgres"
database_url: str = "postgresql://kbuser:kbpass@localhost:5432/knowledge_base"

# deps.py 逻辑
if settings.backend == "postgres":
    session_factory = create_session_factory(settings.database_url)
    chunk_store = PgChunkStore(session_factory)
    asset_store = PgAssetStore(session_factory)
else:
    chunk_store = ChunkStore()
    asset_store = MemoryAssetStore()
# VectorIndex 和 BM25Index 始终用内存实现（阶段 3 迁移）
```

**备选方案**：依赖注入框架（如 `dependency-injector`）——阶段 2 的切换点只有 4 个（chunk_store, asset_store + Document/ParsedElement Repository），框架引入的复杂度超过收益。

### 3. Parser 注册表：简单的 dict 分派

**选择**：`parsers/registry.py` 维护 `dict[str, DocumentParser]`，启动时注册所有解析器，`deps.py`（或调用方）通过 `registry.get(source_type)` 获取解析器。

```python
class ParserRegistry:
    def __init__(self):
        self._parsers: dict[str, DocumentParser] = {}

    def register(self, *parsers: DocumentParser):
        for p in parsers:
            for t in p.SUPPORTED_TYPES:
                self._parsers[t.lower()] = p

    def get(self, source_type: str) -> DocumentParser:
        ...
```

每个 Parser 声明 `SUPPORTED_TYPES: set[str]` 作为类属性。`deps.py` 中替换 `parser = MarkdownParser()` 为 `parser = registry`。

### 4. DOCX 解析器设计

**选择**：`python-docx` 遍历段落和表格，图片通过 `document.inline_shapes` 或解析 `docx` 内部的 `image` 部件提取。

```
DOCX 文档结构映射：
  Document.paragraphs  → ParsedElement(paragraph)
  段落中 Heading style → ParsedElement(title)
  Document.tables      → ParsedElement(table, structured_data)
  docx .zip 内图片     → Asset(image) + ParsedElement(image)
```

表格映射与 MarkdownParser 一致：
```python
structured_data = {
    "table": {
        "caption": "",
        "headers": ["列1", "列2"],
        "rows": [{"cells": [{"text": "...", "asset_ids": []}, ...]}, ...]
    }
}
```

图片提取策略：`python-docx` 的图片 API 有限，采用直接访问 docx zip 包内 `word/media/` 目录的方式提取图片字节，计算 hash，创建 Asset（`status=pending`，`storage_uri=null`，`extracted_text=null`）。阶段 2 不做多模态描述（阶段 5）。

### 5. 评测体系

**选择**：最小可行评测框架。

```text
tests/evaluation/
  eval_dataset.json    # 大模型辅助标注数据
  dataset.py           # 加载 + 校验
  metrics.py           # recall_at_k, mrr
  test_evaluation.py   # pytest 兼容的评测运行器
```

标注数据由大模型基于 query、候选 chunk_id 和 chunk 内容辅助生成，再人工抽检/确认。数据格式（与 DEVELOPMENT.md §14 对齐）：
```json
[
  {
    "query": "上传文档后如何判断解析成功？",
    "expected_chunk_ids": ["chunk_001"],
    "expected_content_contains": ["上传文档", "解析状态", "成功"]
  }
]
```

指标只做两个（按 DEVELOPMENT.md 要求）：`Recall@5` 和 `MRR`。评测脚本作为 pytest 测试运行，CI 友好。

## Risks / Trade-offs

- **[pgvector 扩展未安装]** → `docker-compose.yml` 使用 `pgvector/pgvector:pg16` 镜像已包含扩展，启动时自动可用
- **[pgvector 仅用于元数据存 JSONB 而非向量检索]** → 阶段 2 不依赖 pgvector 向量功能，JSONB 存储 asset_refs / source_refs / metadata 等嵌套结构；若 pgvector 扩展加载失败，核心功能不受影响
- **[DOCX 内嵌图片数量不可控]** → 单文档最大元素数 `max_elements_per_doc` 包含图片元素，超大文档自动截断
- **[内存索引在 PG 模式下仍需重建]** → 阶段 2 的 PG 模式启动时从 `knowledge_chunks` 表全量加载到内存索引（向量需重新 embedding），适合小规模；大规模场景留给阶段 3 Milvus 解决
- **[PG 模式下读取 docx 内容时 source_uri 指向本地文件]** → 阶段 2 `/upload` 仍写本地磁盘（非 MinIO），PG 模式仅持久化元数据，文件读取逻辑不变

## Open Questions

1. **PG 模式下启动时是否自动从 PG 重建内存索引？** — 建议阶段 2 不做自动重建（需要 re-embedding 成本高），PG 模式的典型使用是：启动 → 新入库 → 索引填充。重建逻辑留到阶段 3。
