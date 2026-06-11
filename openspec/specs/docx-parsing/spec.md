# DOCX Parsing

## Purpose

解析 DOCX 文档为统一的 ParseResult（ParsedElement 列表 + Asset 列表），与 MarkdownParser 输出格式完全一致，使下游语义抽取管线无需感知文档格式差异。

## Requirements

### Requirement: 将 DOCX 文档解析为结构化元素

系统 SHALL 将 DOCX 文档解析为 ParsedElement 树，保留文档结构，输出与 MarkdownParser 兼容的 ParseResult。

#### Scenario: 解析含标题和段落的简单 DOCX

- **WHEN** 提交包含 Heading 1/2/3 样式段落和普通段落的 DOCX 文档
- **THEN** 解析器按正确 `sequence_order` 生成类型为 `title`（`metadata.heading_level=1/2/3`）和 `paragraph` 的 ParsedElement
- **AND** `source_location.section_path` 反映标题层级路径

#### Scenario: 解析 DOCX 表格

- **WHEN** DOCX 文档包含带表头行和多行数据的表格
- **THEN** 解析器生成 `table` 元素，其 `structured_data.table` 包含 `caption`、`headers` 和 `rows`
- **AND** 每行的每个单元格保留 `text` 和 `asset_ids`
- **AND** 若表格包含合并单元格，解析器 SHALL 展开合并单元格并复制内容到所有被合并的单元格

#### Scenario: 提取 DOCX 内嵌图片

- **WHEN** DOCX 文档包含内嵌图片
- **THEN** 解析器提取图片字节，计算 `content_hash`，创建 `asset_type="image"` 的 Asset 记录
- **AND** Asset 的 `original_uri` 记录为 `docx://{doc_id}/media/image{N}.{ext}`
- **AND** Asset 的 `status` 为 `pending`，`storage_uri` 为 null，`extracted_text` 为 null
- **AND** 生成对应的 `image` 类型 ParsedElement，`asset_ids` 引用该 Asset

#### Scenario: 解析 DOCX 列表

- **WHEN** DOCX 文档包含无序列表或有序列表
- **THEN** 解析器生成 `list` 容器元素，每个列表项作为 `paragraph` 子元素通过 `parent_element_id` 归属

#### Scenario: 不支持的内嵌对象降级处理

- **WHEN** DOCX 文档包含 OLE 对象、ActiveX 控件或其他无法提取的内嵌对象
- **THEN** 解析器生成 `unknown` 类型 ParsedElement，`text` 包含占位说明，不阻塞整体解析

### Requirement: DOCX 解析器实现统一解析器接口

系统 SHALL 实现 `DocumentParser` 抽象接口，声明 `SUPPORTED_TYPES = {"docx"}`。

#### Scenario: 支持类型检查

- **WHEN** 调用 `supports("docx")`
- **THEN** 返回 `True`

#### Scenario: 不支持的类型

- **WHEN** 调用 `supports("pdf")`
- **THEN** 返回 `False`

#### Scenario: 解析返回 ParseResult

- **WHEN** 解析含标题、段落和表格的 DOCX
- **THEN** 返回 `ParseResult`，包含 `doc`（含更新后的 `source_hash`）、`elements` 和 `assets`
- **AND** 所有 ParsedElement 的 `doc_id` 与输入 Document 一致
