## Why

PDF 是知识库系统阶段 4 路线图中优先级最高的待实现格式，也是企业文档管理中最常见的文档格式之一。当前系统已支持 Markdown、DOCX、HTML、XLSX 和 PPTX 五种格式的入库解析，缺少 PDF 支持导致大量产品手册、技术报告、合同文档等 PDF 文件无法入库检索。阶段 4 其余三种格式（HTML/XLSX/PPTX）均已完成，PDF 是该阶段的最后一个缺口。

## What Changes

- 新增 `PdfParser`（`parsers/pdf_parser.py`），实现 `DocumentParser` 抽象接口，声明 `SUPPORTED_TYPES = {"pdf"}`
- 使用 PyMuPDF（fitz）提取页面文本、图片、超链接和目录大纲，生成统一的 `ParseResult`
- 支持从 `metadata.raw_content`（字节）和 `file://` / `minio://` URI 读取 PDF 内容
- 利用 TOC 大纲和字体大小启发式识别标题层级，构建 `section_path`
- 尝试检测 PDF 内嵌表格，将表格结构存入 `structured_data.table`
- 提取 PDF 内嵌图片，创建 `Asset`（`asset_type="image"`），计算 content_hash 去重
- 识别 PDF 超链接中的视频 URL 和附件 URL，创建对应的 `Asset`
- 在 `ParserRegistry` 注册 PdfParser，与现有五种解析器并列
- 在 `requirements.txt` 中添加 `PyMuPDF>=1.24.0` 依赖
- 编写单元测试（`test_pdf_parser.py`）和入库集成测试（`test_ingestion_pdf.py`）
- 创建 OpenSpec 规格文档 `pdf-parsing/spec.md`

## Capabilities

### New Capabilities

- `pdf-parsing`: PDF 文档解析能力 — 将 PDF 文件解析为统一的 `ParseResult`（ParsedElement + Asset），与现有解析器下游契约保持一致

### Modified Capabilities

<!-- 无现有 capability 的需求变更 -->

## Impact

- **新增文件**: `parsers/pdf_parser.py`、`tests/test_pdf_parser.py`、`tests/test_ingestion_pdf.py`、`openspec/specs/pdf-parsing/spec.md`
- **修改文件**: `parsers/__init__.py`（导出）、`app/core/deps.py`（注册）、`requirements.txt`（依赖）
- **新增依赖**: PyMuPDF（fitz）>= 1.24.0
- **API 影响**: 无 — 纯解析器扩展，入库和检索 API 不变
- **回滚计划**: 移除 PdfParser 注册和新增文件即可，不影响已有功能
