# Markdown Parsing

## Purpose

定义 Markdown 和纯文本（.md / .txt）文档解析能力，将文档内容转换为统一的 `ParseResult`、`ParsedElement` 和 `Asset`，与 DOCX、XLSX 等解析下游契约保持兼容。

## Requirements

### Requirement: 将 Markdown 文档解析为统一结构

系统 SHALL 将 `.md`、`.markdown`、`.txt` 和 `.text` 文档解析为统一的 `ParseResult`，输出 `Document`、`ParsedElement` 和 `Asset`。

#### Scenario: 解析 Markdown 标题层级

- **GIVEN** Markdown 文档包含 `#`、`##` 和 `###` 标题
- **WHEN** 调用 `MarkdownParser.parse(doc, content)`
- **THEN** 系统为每个标题生成 `title` 类型 ParsedElement
- **AND** `metadata.heading_level` 记录标题等级
- **AND** `source_location.section_path` 按标题层级维护路径

#### Scenario: 解析纯文本文件

- **GIVEN** 纯文本 `.txt` 文件无任何 Markdown 标记
- **WHEN** 调用 `MarkdownParser.parse(doc, content)`
- **THEN** 系统将全部文本生成为 `paragraph` 类型 ParsedElement
- **AND** 解析不因缺少 Markdown 标记而失败

### Requirement: 解析引用块并保留语义标记

系统 SHALL 在解析 Markdown `>` 引用块时保留内容，并在段落 metadata 中标记 `blockquote=true`。

#### Scenario: 单层引用块

- **GIVEN** Markdown 文档包含 `> 这是引用的文本`
- **WHEN** 解析该文档
- **THEN** 系统生成 `paragraph` 类型 ParsedElement
- **AND** 元素 `metadata.blockquote` 为 `true`
- **AND** `text` 为 `"这是引用的文本"`

### Requirement: 段落内链接 URL 提取为资源

系统 SHALL 从 Markdown 链接语法 `[text](url)` 中提取 URL，当 URL 指向文件附件、视频或图片时创建对应 Asset。普通网页链接保留在 `metadata.link_urls` 中。图片 Asset 通过 `asset_ids` 关联到包含它的段落。

#### Scenario: 附件链接创建 Asset

- **GIVEN** Markdown 文档包含 `[下载手册](https://example.com/manual.pdf)`
- **WHEN** 解析该文档
- **THEN** 系统创建 `asset_type="attachment"` 的 Asset
- **AND** 对应段落的 `asset_ids` 引用该 Asset

#### Scenario: 视频链接创建 Asset

- **GIVEN** Markdown 文档包含 `[演示视频](https://example.com/demo.mp4)`
- **WHEN** 解析该文档
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** 对应段落的 `asset_ids` 引用该 Asset

#### Scenario: 普通网页链接保留在 metadata

- **GIVEN** Markdown 文档包含 `[Google](https://www.google.com)`
- **WHEN** 解析该文档
- **THEN** 元素 `metadata.link_urls` 记录 `["https://www.google.com"]`
- **AND** 不创建额外 Asset

### Requirement: 表格单元格内资源关联

系统 SHALL 在 Markdown 表格单元格中识别图片和链接，将对应的 Asset 关联到单元格的 `asset_ids` 中。

#### Scenario: 表格单元格包含图片

- **GIVEN** Markdown 表格单元格包含 `![架构图](https://example.com/a.png)`
- **WHEN** 解析该文档
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** 对应单元格的 `structured_data.table.rows[].cells[].asset_ids` 引用该 Asset
- **AND** 表格级 `asset_ids` 汇总所有单元格的 Asset ID

#### Scenario: 表格单元格包含文档链接

- **GIVEN** Markdown 表格单元格包含 `[说明文档](https://example.com/doc.pdf)`
- **WHEN** 解析该文档
- **THEN** 系统创建 `asset_type="attachment"` 的 Asset
- **AND** 对应单元格的 `asset_ids` 引用该 Asset

### Requirement: 使用公共基础设施

系统 SHALL 使用 `parsers/utils.py` 的共享正则和函数，不再内联重复代码。

#### Scenario: CONTENT_IS_TEXT 声明

- **WHEN** 检查 `MarkdownParser.CONTENT_IS_TEXT`
- **THEN** 值为 `True`

### Requirement: 实现统一解析器接口

系统 SHALL 实现 `DocumentParser` 抽象接口，声明 `SUPPORTED_TYPES = {"markdown", "md", "txt", "text"}`。

#### Scenario: 支持类型检查

- **WHEN** 调用 `supports("markdown")`、`supports("md")`、`supports("txt")`、`supports("text")`
- **THEN** 全部返回 `True`

#### Scenario: 大小写不敏感

- **WHEN** 调用 `supports("MARKDOWN")`
- **THEN** 返回 `True`
