## Why

阶段 4 已经通过 XLSX 和 HTML 验证了多格式解析接入 ParserRegistry、入库管线和语义抽取链路的方式。PPTX 是业务知识库中常见的培训材料、方案汇报、产品介绍和流程说明载体，且与 DOCX/XLSX 同属 Office Open XML 体系，适合在现有阶段 4 基础上继续补齐 Office 文档族。

相比 PDF，PPTX 的结构化信息更明确：幻灯片、占位符、文本框、表格、图片和媒体关系可以通过稳定库读取，首版可以用较小边界获得较可靠的解析质量。本变更聚焦 `.pptx` 演示文稿解析，不扩大到 PDF、旧版 `.ppt`、OCR、动画语义或精确版面还原，避免阶段 4 后续纵切一次跨入复杂视觉理解。

## What Changes

- 新增 PPTX 解析能力，基于 `python-pptx` 将演示文稿解析为统一 `ParseResult`。
- 按幻灯片顺序解析内容，为每张幻灯片保留 `slide_index`、`slide_number`、幻灯片标题和来源上下文。
- 将标题占位符或首个标题形状映射为 `title` 元素，并维护 `source_location.section_path`。
- 将文本框、正文占位符和普通形状文本映射为 `paragraph` 或 `list` 结构，保留项目符号层级和形状位置元数据。
- 将 PPTX 表格形状映射为兼容 Markdown/DOCX/XLSX/HTML 的 `structured_data.table`。
- 提取内嵌图片为 `Asset(asset_type=image, status=pending)`，生成可追溯的 `image` 元素并关联 `asset_ids`。
- 识别文本和关系中的视频 URL、音频/视频媒体、附件或外部链接，创建或保留 `video` / `attachment` 资源候选；阶段 4 不下载、不递归解析、不做多模态理解。
- 对暂不支持的 SmartArt、图表、OLE 对象、复杂组合形状等生成 `unknown` 或降级文本元素，避免静默丢失可追溯信息。
- 注册 `PptxParser`，使 `/ingest` 可通过 `source_type="pptx"` 自动选择解析器。
- 新增 PPTX 解析器、注册表和入库分发测试，覆盖文本、列表、表格、图片、链接、无效文件和空演示文稿边界。

## Capabilities

### New Capabilities

- `pptx-parsing`：定义 PPTX 演示文稿解析为统一 ParsedElement/Asset 输出的行为，包括幻灯片、标题、段落、列表、表格、图片、视频/附件链接和不支持对象的降级处理。

### Modified Capabilities

- `document-ingestion`：将当前支持格式从 Markdown/TXT/DOCX/XLSX/HTML/HTM 扩展为包含 PPTX，并要求入库管线通过 ParserRegistry 分发到 PptxParser。
- `parser-registry`：增加 PPTX 解析器注册和 `source_type="pptx"` 的分发要求。
- `asset-lifecycle`：明确 PPTX 解析阶段识别图片、视频、音频和附件资源时的 Asset 类型、状态和不下载边界。

## Impact

受影响代码模块：

- `knowledge_base_system/parsers/`：新增 PPTX 解析器。
- `knowledge_base_system/app/core/deps.py`：注册 `PptxParser`。
- `knowledge_base_system/requirements.txt`：新增 `python-pptx` 依赖。
- `knowledge_base_system/tests/`：新增 PPTX 解析器、注册表和入库分发相关测试。
- `openspec/specs/pptx-parsing`：新增 PPTX 解析能力规格。
- `openspec/specs/document-ingestion`、`openspec/specs/parser-registry`、`openspec/specs/asset-lifecycle`：更新支持格式和资源识别要求。

公共 API 保持向后兼容：`/upload` 与 `/ingest` 请求结构不变，调用方只需在入库时传入 `source_type="pptx"`。

对现有功能的影响：

- Markdown/TXT/DOCX/XLSX/HTML 解析、语义抽取、资源处理、索引和检索链路不应改变。
- PPTX 解析失败只影响对应入库任务，不应影响其他文档格式。
- 首版不支持旧版 `.ppt`、受密码保护演示文稿、动画/切换效果、母版完整语义、SmartArt/图表深度理解、OCR 或复杂版面还原。

回滚计划：

- 从 ParserRegistry 中移除 `PptxParser` 注册即可停止新的 PPTX 入库。
- 移除 `python-pptx` 依赖和新增解析器文件，不影响现有 Markdown/TXT/DOCX/XLSX/HTML 链路。
- 已入库的 PPTX 知识块可按 `doc_id`、`source_type="pptx"` 或入库任务删除并重建，索引可通过现有删除和重建流程恢复。
