## 1. 解析器注册机制

- [x] 1.1 新建 `parsers/registry.py`：实现 `ParserRegistry` 类（register/get 方法），支持按 `source_type`（大小写不敏感）分派解析器，重复注册时覆盖并 WARNING 日志，未匹配类型时抛出明确错误并列出已注册类型
- [x] 1.2 为 `MarkdownParser` 添加 `SUPPORTED_TYPES` 类属性（`{"markdown", "md", "txt", "text"}`）
- [x] 1.3 在 `deps.py` 中创建全局 `parser_registry` 实例并注册 `MarkdownParser`
- [x] 1.4 修改 `IngestionPipeline.__init__`：接受 `parser_registry` 参数（替代 `parser: DocumentParser`），在 `_run` 中通过 `parser_registry.get(doc.source_type)` 获取解析器
- [x] 1.5 编写 `tests/test_parser_registry.py`：覆盖注册、大小写分派、未匹配报错、重复注册覆盖

## 2. DOCX 解析器

- [x] 2.1 新建 `parsers/docx_parser.py`：实现 `DocxParser(DocumentParser)`，`SUPPORTED_TYPES = {"docx"}`，基于 `python-docx` 解析段落（含 Heading 样式映射为 title）、列表和表格
- [x] 2.2 实现 DOCX 内嵌图片提取：通过 zipfile 直接访问 `word/media/` 目录提取图片字节，计算 `content_hash`，创建 Asset 记录（`status=pending`）
- [x] 2.3 实现 DOCX 表格映射：将 `python-docx` 表格转为 `structured_data.table`（含 caption/headers/rows），合并单元格展开处理
- [x] 2.4 处理不支持的内嵌对象（OLE/ActiveX）：生成 `unknown` 类型 ParsedElement，不阻塞整体解析
- [x] 2.5 在 `deps.py` 中注册 `DocxParser` 到 `parser_registry`
- [x] 2.6 编写 `tests/test_docx_parser.py`：覆盖段落/标题、表格、内嵌图片、列表、不支持对象降级

## 3. PostgreSQL 基础设施

- [x] 3.1 新建 `app/db/engine.py`：实现 `create_engine` 和 `sessionmaker` 工厂（从 `settings.database_url` 读取），连接池大小为 5
- [x] 3.2 新建 `app/db/session.py`：实现 `get_db` FastAPI 依赖（yield Session，finally 中 close）
- [x] 3.3 新建 `app/db/models.py`：定义 SQLAlchemy ORM 类 `DbDocument`、`DbParsedElement`、`DbAsset`、`DbKnowledgeChunk`，嵌套字段（asset_refs/source_refs/metadata 等）使用 JSONB 类型
- [x] 3.4 实现 `Base.metadata.create_all` 在 postgres 模式应用启动时自动建表
- [x] 3.5 编写 `tests/test_db_models.py`：验证表创建、基本 CRUD 操作、JSONB 字段读写

## 4. PostgreSQL Repository 层

- [x] 4.1 新建 `app/db/repositories/__init__.py` 和 `app/db/repositories/base.py`：定义 `BaseRepository` 抽象基类
- [x] 4.2 新建 `app/db/repositories/documents.py`：`DocumentRepository`，实现 `create(doc: Document) -> Document`、`get(doc_id) -> Document | None`、`update(doc) -> Document`
- [x] 4.3 新建 `app/db/repositories/elements.py`：`ParsedElementRepository`，实现 `create_batch(elements: list[ParsedElement])` 和 `get_by_doc_id(doc_id) -> list[ParsedElement]`
- [x] 4.4 新建 `app/db/repositories/chunks.py`：`PgChunkStore`，实现 `put(chunk)`、`get(chunk_id)`、`get_batch(chunk_ids)`（匹配 `ChunkStore` 接口）
- [x] 4.5 新建 `app/db/repositories/assets.py`：`PgAssetStore`，实现 `put(asset)`、`get(asset_id)`、`delete(asset_id)`（匹配 `AssetStore` ABC）
- [x] 4.6 编写 `tests/test_db_repositories.py`：覆盖各 Repository 的创建、查询、更新操作，验证 Pydantic ↔ SQLAlchemy 转换正确

## 5. 配置与依赖注入重构

- [x] 5.1 扩展 `app/core/config.py`：新增 `BACKEND`（`memory`/`postgres`，默认 `memory`）和 `DATABASE_URL` 配置项
- [x] 5.2 重构 `app/core/deps.py`：根据 `BACKEND` 值创建对应实现（memory 时使用现有 `Memory*` 实例，postgres 时使用 `Pg*` 实例），VectorIndex 和 BM25Index 始终保持内存实现
- [x] 5.3 确保 `BACKEND=memory` 时所有现有 26 个测试保持通过（向后兼容验证）

## 6. 评测体系

- [x] 6.1 一次性准备评测数据集：入库标注用源文档 → 记录实际 chunk_id 和 chunk 内容 → 使用大模型辅助标注 `expected_chunk_ids` 和 `expected_content_contains` → 人工抽检/确认标注结果 → 生成 `tests/evaluation/eval_dataset.json`（≥20 条，覆盖陈述型/关系型/流程型三种查询意图）
- [x] 6.2 新建 `tests/evaluation/dataset.py`：实现数据加载函数（`load_dataset() -> list[EvalItem]`）和完整性校验（必需字段检查）
- [x] 6.3 新建 `tests/evaluation/metrics.py`：实现 `recall_at_k(results, expected, k=5) -> float` 和 `mrr(results, expected) -> float`
- [x] 6.4 新建 `tests/evaluation/test_evaluation.py`：评测脚本，遍历数据集执行 `RetrievalPipeline.search()`，计算 Recall@5 和 MRR，输出 Markdown 报告到 `tests/results/`

## 7. 集成验证

- [x] 7.1 启动 `docker-compose up -d`，验证 PostgreSQL 连接正常
- [x] 7.2 运行 `pytest tests/ -v` 确认全部测试通过（含新增的 DB/DOCX/registry/eval 测试）
- [x] 7.3 手动验证 PG 模式端到端：上传 Markdown → 入库 → 检索 → 重启应用 → 确认数据保留（chunk 可通过 API 查询）
- [x] 7.4 手动验证 DOCX 解析端到端：上传 DOCX → 入库 → 检索 → 确认结果包含 DOCX 内容
- [x] 7.5 运行评测脚本，记录基线 Recall@5 和 MRR 值
