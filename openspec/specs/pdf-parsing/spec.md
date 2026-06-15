# PDF Parsing

## Purpose

定义 PDF 文档解析能力，将 PDF 文件内容转换为与现有 Markdown、DOCX、HTML、XLSX、PPTX 解析下游契约兼容的 `ParseResult`、`ParsedElement` 和 `Asset`。

> 同步自 change `phase-4-pdf-parsing`，日期 2026-06-15。

## Requirements

### Requirement: 将 PDF 文档解析为统一结构

系统 SHALL 将 `.pdf` 文档解析为统一的 `ParseResult`，输出 `Document`、`ParsedElement` 和 `Asset`，并与 MarkdownParser、DocxParser、XlsxParser、HtmlParser 和 PptxParser 的下游契约保持兼容。

#### Scenario: 解析多页 PDF 文档

- **GIVEN** 一个包含多页文本内容的 PDF 文档
- **WHEN** 调用 `PdfParser.parse(doc)`
- **THEN** 系统按页码顺序生成 ParsedElement
- **AND** 每个元素 `source_location.page` 记录所在页码
- **AND** `result.doc.source_hash` 以 `sha256:` 开头
- **AND** 所有 ParsedElement 的 `doc_id` 与输入 Document 一致

#### Scenario: 利用 TOC 识别标题层级

- **GIVEN** 一个 PDF 文档包含目录大纲（TOC），其中一级条目为 "第一章 概述"、二级条目为 "1.1 背景"
- **WHEN** 解析该 PDF 文档
- **THEN** 系统为 TOC 条目对应的文本生成 `title` 类型 ParsedElement
- **AND** `title.metadata.heading_level` 与 TOC 层级对应
- **AND** `source_location.section_path` 按标题层级维护当前路径

#### Scenario: 无 TOC 时用字体大小识别标题

- **GIVEN** 一个 PDF 文档不含 TOC，但某文本块字体显著大于正文（如 >= 14pt）
- **WHEN** 解析该 PDF 文档
- **THEN** 系统 SHALL 将该大字体文本块生成 `title` 类型 ParsedElement
- **AND** 普通字体文本块生成 `paragraph` 类型 ParsedElement

#### Scenario: 用粗体识别子标题

- **GIVEN** 一个 PDF 文档不含 TOC，正文为 12pt Normal，子标题为 12pt Bold
- **WHEN** 解析该 PDF 文档
- **THEN** 系统 SHALL 将粗体短文本块（≤ 80 字符）生成 `title` 类型 ParsedElement
- **AND** `title.metadata.heading_level` 标记为较低层级（如 3）
- **AND** 同字号的非粗体文本块仍为 `paragraph`

#### Scenario: 标题路径在元素间正确传播

- **GIVEN** PDF 文档包含一级标题 "产品概述" 和其下的二级标题 "功能特性" 以及若干正文段落
- **WHEN** 解析该 PDF 文档
- **THEN** 一级标题之后的段落 `section_path` 为 `["产品概述"]`
- **AND** 二级标题之后的段落 `section_path` 为 `["产品概述", "功能特性"]`
- **AND** 二级标题的 `section_path` 为 `["产品概述"]`（自身不含入路径）

#### Scenario: 空 PDF 文档降级为失败

- **GIVEN** 文档声明 `source_type="pdf"` 但没有可提取的文本内容
- **WHEN** 入库管线调用解析器
- **THEN** 入库 job 状态变为 `failed`
- **AND** 错误信息包含 PDF 解析失败原因

#### Scenario: 扫描件 PDF 给出明确错误提示

- **GIVEN** 一个 PDF 文档有页面但所有页面均为图片（无可提取文本层）
- **WHEN** 解析该 PDF 文档
- **THEN** 系统 SHALL 抛出 `ValueError`
- **AND** 错误信息区分"文件为空"和"可能为扫描件，无可提取文本"，建议用户使用 OCR 预处理

### Requirement: 按阅读顺序提取 PDF 文本内容

系统 SHALL 按页面内自上而下、自左而右的阅读顺序提取 PDF 文本块，生成 `paragraph` 类型 ParsedElement，保留来源页码和位置信息。

#### Scenario: 按页面顺序提取文本

- **GIVEN** 一个两页 PDF 文档，每页包含多个文本段落
- **WHEN** 解析该 PDF 文档
- **THEN** 所有 ParsedElement 的 `sequence_order` 按页码递增、页内按阅读顺序递增
- **AND** 每个元素的 `source_location.page` 记录正确页码
- **AND** 第二页的元素不出现在第一页元素之前

#### Scenario: 合并同一段落内的文本碎片

- **GIVEN** PDF 页面中同一段落的文本被 PDF 内部结构拆分为多个小块
- **WHEN** 解析该页面
- **THEN** 系统 SHALL 将相邻且字体一致的文本碎片合并为一个 `paragraph` 元素
- **AND** 合并后文本保持可读性

#### Scenario: 基于间距分离不同段落

- **GIVEN** PDF 页面中两个相邻文本块使用相同字体，但垂直间距大于 1.5 倍行高
- **WHEN** 解析该页面
- **THEN** 系统 SHALL 将它们生成为两个独立的 `paragraph` 元素
- **AND** 不因字体一致而错误合并

#### Scenario: 过滤页眉页脚重复文本

- **GIVEN** 一个 5 页 PDF 文档，每页顶部包含相同的 "产品手册 v2.0" 页眉，底部包含页码
- **WHEN** 解析该 PDF 文档
- **THEN** 系统 SHALL 不将页眉和页脚文本生成为 ParsedElement
- **AND** 正文内容不受影响

#### Scenario: 短文档不过滤可能为标题的顶部文本

- **GIVEN** 一个 2 页 PDF 文档，第 1 页顶部有大字体文档标题
- **WHEN** 解析该 PDF 文档
- **THEN** 系统 SHALL 保留该标题文本为 `title` 元素
- **AND** 不因位置靠上而误判为页眉

#### Scenario: 处理编码异常字符

- **GIVEN** PDF 文档包含特殊编码或无法映射的字符
- **WHEN** 解析该 PDF
- **THEN** 系统 SHALL 使用替换字符或跳过，不因编码问题导致整个解析失败

### Requirement: 将 PDF 表格解析为表格元素

系统 SHALL 尝试检测 PDF 中的表格结构，将其解析为 `table` 类型 ParsedElement，保留行列结构用于语义层转写自然语言。

#### Scenario: 检测有边框表格

- **GIVEN** PDF 页面包含有明确边框线的表格，首行为表头
- **WHEN** 调用 `page.find_tables()` 检测到表格
- **THEN** 系统生成一个 `table` 类型 ParsedElement
- **AND** `structured_data.table.headers` 来自首行
- **AND** `structured_data.table.rows` 包含后续数据行
- **AND** 每个单元格至少包含 `text` 和行/列位置信息

#### Scenario: 表格检测失败时降级为文本

- **GIVEN** PDF 页面包含无边框表格或 `find_tables()` 未检测到表格
- **WHEN** 解析该页面
- **THEN** 系统 SHALL 将表格区域的文本生成 `paragraph` 类型 ParsedElement
- **AND** 文本内容保留原始行列信息的字符表示
- **AND** 解析流程不因表格检测失败而中断

#### Scenario: find_tables API 不可用时安全降级

- **GIVEN** 运行环境中的 PyMuPDF 版本低于 1.23.0（无 `find_tables` 方法）
- **WHEN** 解析包含表格的 PDF 页面
- **THEN** 系统 SHALL 通过 `hasattr` 检测并跳过表格检测
- **AND** 页面所有内容按文本块正常提取
- **AND** 解析流程不因缺少 API 而崩溃

### Requirement: 提取 PDF 中的图片、视频链接和附件资源

系统 SHALL 提取 PDF 内嵌图片并创建 image Asset；识别超链接中的视频 URL 和附件 URL，创建或关联 Asset，并在 ParsedElement 中保留 `asset_ids`。

#### Scenario: 提取内嵌图片资源

- **GIVEN** PDF 文档第 3 页包含一张内嵌图片
- **WHEN** 解析该 PDF 文档
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** Asset 的 `content_hash` 以 `sha256:` 开头
- **AND** Asset 的 `status` 为 `pending`
- **AND** Asset 的 `original_uri` 包含页面引用信息
- **AND** Asset 保留原始字节数据供后续 MinIO 上传
- **AND** 系统生成 `image` 类型 ParsedElement 并通过 `asset_ids` 引用该 Asset
- **AND** ParsedElement 的 `source_location.page` 为图片所在页码

#### Scenario: 识别超链接中的视频 URL

- **GIVEN** PDF 文档包含指向 `https://example.com/demo.mp4` 的超链接
- **WHEN** 解析该 PDF 文档
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** Asset 的 `original_uri` 为该视频 URL
- **AND** Asset 的 `status` 为 `pending`
- **AND** 阶段 4 不下载或理解视频内容

#### Scenario: 识别超链接中的附件 URL

- **GIVEN** PDF 文档包含指向 `https://example.com/manual.pdf` 的超链接
- **WHEN** 解析该 PDF 文档
- **THEN** 系统 SHALL 保留该链接的来源信息
- **AND** 若创建 Asset，则 Asset 的 `asset_type` 为 `attachment`
- **AND** 阶段 4 不下载或递归解析该附件

#### Scenario: 去重相同图片资源

- **GIVEN** 同一 PDF 文档多处使用相同的内嵌图片（相同 content_hash）
- **WHEN** 解析该文档
- **THEN** 系统 SHALL 避免重复创建等价 image Asset
- **AND** 多个 ParsedElement 可以通过 `asset_ids` 引用同一 Asset

### Requirement: PDF 解析器实现统一解析器接口

系统 SHALL 实现 `DocumentParser` 抽象接口，声明 `SUPPORTED_TYPES = {"pdf"}`，并支持从 `metadata.raw_content`（字节）或 `file://` / `minio://` 入库链路提供的字节内容中解析 PDF。

#### Scenario: 支持类型检查

- **WHEN** 调用 `PdfParser.supports("pdf")`
- **THEN** 返回 `True`

#### Scenario: 大小写不敏感

- **WHEN** 调用 `PdfParser.supports("PDF")` 或 `PdfParser.supports("Pdf")`
- **THEN** 返回 `True`

#### Scenario: 无效 PDF 文件降级为失败

- **GIVEN** 文档声明 `source_type="pdf"` 但内容不是有效 PDF 文件或已损坏
- **WHEN** 入库管线调用解析器
- **THEN** 入库 job 状态变为 `failed`
- **AND** 错误信息包含 PDF 解析失败原因

#### Scenario: 加密 PDF 降级为失败

- **GIVEN** 文档声明 `source_type="pdf"` 且内容为已加密 PDF
- **WHEN** 入库管线调用解析器
- **THEN** 入库 job 状态变为 `failed`
- **AND** 错误信息明确说明文档已加密

#### Scenario: 从 file:// URI 读取 PDF

- **GIVEN** Document 的 `source_uri` 为 `file:///path/to/document.pdf`
- **WHEN** 调用 `PdfParser.parse(doc)`
- **THEN** 系统从文件路径读取 PDF 字节并解析
- **AND** `result.doc.source_hash` 以 `sha256:` 开头
