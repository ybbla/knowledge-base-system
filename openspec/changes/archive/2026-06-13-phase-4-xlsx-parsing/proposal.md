## Why

当前系统已经打通 Markdown/TXT/DOCX 入库、语义抽取、Milvus/MinIO 混合检索链路，但阶段 4 的多格式解析尚未落地。XLSX 是业务知识库中最常见的结构化资料来源之一，优先支持 XLSX 可以直接提升表格类知识的入库覆盖率，并复用现有“解析结构化表格 → LLM 转写自然语言知识块”的主链路。

本变更先聚焦 `.xlsx` 工作簿解析，不扩大到 PDF/HTML/PPTX，避免阶段 4 一次性跨太多格式导致边界失控。

## What Changes

- 新增 XLSX 解析能力，基于 `openpyxl` 将工作簿解析为统一的 `ParseResult`。
- 每个可见工作表生成工作表级 `title` 元素，并保留工作表名称、顺序等来源信息。
- 将连续非空单元格区域识别为 `table` 元素，输出与 Markdown/DOCX 表格兼容的 `structured_data.table`。
- 展开合并单元格，将合并区域左上角值复制到范围内，减少表格语义丢失。
- 保留单元格范围、公式处理方式、超链接等来源元数据，便于追溯和后续增强。
- 识别单元格中的视频链接并创建 `Asset(asset_type=video)`，识别普通超链接作为附件类资源候选。
- 注册 `XlsxParser`，使 `/ingest` 可通过 `source_type="xlsx"` 自动选择解析器。
- 新增 XLSX 解析测试，覆盖工作表、表格区域、合并单元格、公式、超链接和空/隐藏工作表边界。

## Capabilities

### New Capabilities

- `xlsx-parsing`: 定义 XLSX 工作簿解析为统一 ParsedElement/Asset 输出的行为，包括工作表、表格区域、合并单元格、公式、超链接和边界处理。

### Modified Capabilities

- `document-ingestion`: 将当前支持格式从 Markdown/TXT/DOCX 扩展为包含 XLSX，并要求入库管线通过 ParserRegistry 分派到 XlsxParser。
- `parser-registry`: 增加 XLSX 解析器注册和 `source_type="xlsx"` 的分派要求。

## Impact

受影响代码模块：

- `knowledge_base_system/parsers/`: 新增 XLSX 解析器。
- `knowledge_base_system/app/core/deps.py`: 注册 `XlsxParser`。
- `knowledge_base_system/requirements.txt`: 新增 `openpyxl` 依赖。
- `knowledge_base_system/tests/`: 新增 XLSX 解析器和注册表相关测试。
- `openspec/specs/document-ingestion` 与 `openspec/specs/parser-registry`: 行为范围扩展到 XLSX。

公共 API 保持向后兼容：`/upload` 与 `/ingest` 请求结构不变，调用方仅需在入库时传入 `source_type="xlsx"`。

对现有功能的影响：

- Markdown/TXT/DOCX 解析、语义抽取、资源处理、索引和检索链路不应改变。
- XLSX 解析失败只影响对应入库任务，不应影响其他文档格式。
- 首版不支持 `.xls`、受密码保护工作簿、宏执行、OCR 或复杂 Excel 图表语义理解。

回滚计划：

- 从 ParserRegistry 中移除 `XlsxParser` 注册即可停止新 XLSX 入库。
- 移除 `openpyxl` 依赖和新增解析器文件，不影响现有 Markdown/TXT/DOCX 链路。
- 已入库的 XLSX 知识块可按 `doc_id`、`source_type="xlsx"` 或入库任务进行删除/重建，索引可通过现有删除和重建流程恢复。
