## Why

阶段 1 已将 Markdown 文档的完整入库→检索链路跑通（26 tests pass），但存在两个关键瓶颈：**重启即丢数据**（全部在内存）和**仅支持 Markdown/TXT**（无法处理最常见的 DOCX 格式）。阶段 2 引入 PostgreSQL 持久化和 DOCX 解析，使系统具备生产环境的基本可靠性。

## What Changes

- **新增 PostgreSQL 持久化层**：SQLAlchemy 映射 Document / ParsedElement / Asset / KnowledgeChunk 四个核心实体，实现 Repository 模式封装 CRUD，重启应用数据完整保留
- **新增 DOCX 解析器**：基于 python-docx 实现段落、标题、表格、内嵌图片提取，输出统一的 ParseResult
- **新增解析器注册机制**：按 `source_type` 自动选择对应解析器，消除 `deps.py` 中硬编码的 `MarkdownParser`
- **新增评测体系**：构建 ≥20 条大模型辅助标注、人工抽检确认的查询-答案评测集，实现 Recall@5 和 MRR 自动化计算脚本
- **重构依赖注入层**：`deps.py` 支持通过 `BACKEND` 环境变量在内存模式和 PostgreSQL 模式之间切换，内存模式保留为开发默认值

## Capabilities

### New Capabilities
- `docx-parsing`: DOCX 文档解析，提取文本、表格结构和内嵌图片，统一输出为 ParseResult
- `parser-registry`: 解析器注册与自动选择，根据 Document.source_type 匹配对应解析器
- `postgresql-persistence`: PostgreSQL 持久化核心实体元数据（Document / ParsedElement / Asset / KnowledgeChunk），含 pgvector 扩展部署
- `evaluation-framework`: 评测数据集管理、Recall@5 和 MRR 指标自动化计算

### Modified Capabilities
- `document-ingestion`: 解析器选择从硬编码 MarkdownParser 改为通过 ParserRegistry 按 source_type 匹配；入库管线需支持从 PostgreSQL 读写元数据

## Impact

- **新增依赖**：sqlalchemy, psycopg2-binary, pgvector, python-docx（已在 requirements.txt 中声明，phase2 开始实际使用）
- **新增模块**：`app/db/`（engine, session, models, repositories）、`parsers/registry.py`、`parsers/docx_parser.py`、`tests/evaluation/`
- **修改文件**：`app/core/deps.py`（可切换后端）、`app/core/config.py`（新增 DATABASE_URL、BACKEND 等配置项）
- **基础设施**：`docker-compose.yml` 已定义 pgvector/pg16 服务，`docker compose up -d` 即可启动
- **无破坏性变更**：默认 `BACKEND=memory`，现有 26 个测试全部保持通过
