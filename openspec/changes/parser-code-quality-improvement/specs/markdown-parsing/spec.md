# Markdown Parsing

## Purpose

定义 Markdown 和纯文本（.md / .txt）文档解析能力，将文档内容转换为统一的 `ParseResult`、`ParsedElement` 和 `Asset`，与 DOCX、PDF、HTML、PPTX、XLSX 解析下游契约保持兼容。

## Requirements

### Requirement: 将 Markdown 文档解析为统一结构

系统 SHALL 将 `.md`、`.markdown`、`.txt` 和 `.text` 文档解析为统一的 `ParseResult`，输出 `Document`、`ParsedElement` 和 `Asset`，与其他解析器的下游契约保持兼容。

#### Scenario: 解析 Markdown 标题层级

- **GIVEN** 一个 Markdown 文档包含 `#`、`##` 和 `###` 标题
- **WHEN** 调用 `MarkdownParser.parse(doc)`
- **THEN** 系统为每个标题生成一个 `title` 类型 ParsedElement
- **AND** `title.text` 为标题文本（去除 `#` 标记）
- **AND** `metadata.heading_level` 记录对应标题等级
- **AND** `source_location.section_path` 按标题层级维护当前路径

#### Scenario: 返回 ParseResult

- **GIVEN** 一个包含标题和正文的 Markdown 文档
- **WHEN** 调用 `MarkdownParser.parse(doc)`
- **THEN** 系统返回 `ParseResult`
- **AND** `result.doc.source_hash` 以 `sha256:` 开头
- **AND** 所有 ParsedElement 的 `doc_id` 与输入 Document 一致

#### Scenario: 解析纯文本文件

- **GIVEN** 一个纯文本 `.txt` 文件
- **WHEN** 调用 `MarkdownParser.parse(doc)`
- **THEN** 系统将全部文本内容生成为 `paragraph` 类型 ParsedElement
- **AND** 解析不因缺少 Markdown 标记而失败

### Requirement: 将 Markdown 正文结构解析为元素

系统 SHALL 将 Markdown 正文中的段落、引用块、列表、代码块和表格解析为统一 ParsedElement，保留文档顺序和来源上下文。

#### Scenario: 解析段落

- **GIVEN** Markdown 文档在正文中包含普通段落
- **WHEN** 解析该 Markdown 文档
- **THEN** 系统生成 `paragraph` 类型 ParsedElement
- **AND** 段落文本为去除 Markdown 标记后的可读文本

#### Scenario: 解析引用块并保留语义

- **GIVEN** Markdown 文档包含 `> 这是引用的内容` 引用块
- **WHEN** 解析该 Markdown 文档
- **THEN** 系统生成 `paragraph` 类型 ParsedElement
- **AND** 元素 `metadata` 中 `blockquote` 设为 `true`
- **AND** 引用文本内容正常保留

#### Scenario: 解析有序和无序列表

- **GIVEN** Markdown 文档包含无序列表（`-` 或 `*`）和有序列表（`1.`）
- **WHEN** 解析该 Markdown 文档
- **THEN** 系统生成 `list` 类型容器元素
- **AND** 每个列表项生成归属于该容器的 `paragraph` 子元素
- **AND** 列表容器 metadata 记录 `ordered=true` 或 `ordered=false`

#### Scenario: 解析代码块

- **GIVEN** Markdown 文档包含围栏代码块（` ```python `）
- **WHEN** 解析该 Markdown 文档
- **THEN** 系统生成 `code` 类型 ParsedElement
- **AND** `text` 保留代码文本
- **AND** `metadata.language` 记录 `"python"`

#### Scenario: 解析表格

- **GIVEN** Markdown 文档包含 `| --- |` 语法表格
- **WHEN** 解析该 Markdown 文档
- **THEN** 系统生成 `table` 类型 ParsedElement
- **AND** `structured_data.table.headers` 来自表头行
- **AND** `structured_data.table.rows` 包含后续数据行

### Requirement: 识别 Markdown 中的图片和视频资源

系统 SHALL 识别 Markdown 中的图片语法（`![alt](url)`）和视频链接，创建或关联 Asset，并在 ParsedElement 中保留 `asset_ids`。

#### Scenario: 识别图片资源

- **GIVEN** Markdown 文档包含 `![logo](https://example.com/logo.png)`
- **WHEN** 解析该 Markdown 文档
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** Asset 的 `original_uri` 为 `https://example.com/logo.png`
- **AND** Asset metadata 记录 `alt="logo"`

#### Scenario: 识别视频链接

- **GIVEN** Markdown 文档包含视频 URL 或 `![video](https://example.com/demo.mp4)`
- **WHEN** 解析该 Markdown 文档
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** Asset 的 `original_uri` 为该视频 URL

### Requirement: 提取 Markdown 链接 URL 为资源

系统 SHALL 从 Markdown 链接语法 `[text](url)` 中提取 URL，当 URL 指向已知附件类型或外部资源时创建 Asset。

#### Scenario: 提取附件链接

- **GIVEN** Markdown 文档包含 `[下载手册](https://example.com/manual.pdf)`
- **WHEN** 解析该 Markdown 文档
- **THEN** 系统创建 `asset_type="attachment"` 的 Asset
- **AND** Asset 的 `original_uri` 为 `https://example.com/manual.pdf`
- **AND** 对应 ParsedElement 的 `asset_ids` 引用该 Asset

#### Scenario: 普通链接不创建资源

- **GIVEN** Markdown 文档包含 `[Google](https://www.google.com)` 普通网页链接
- **WHEN** 解析该 Markdown 文档
- **THEN** 链接 URL 信息保留在元素 metadata 中
- **AND** 不创建额外的 Asset（非附件/视频/图片类型）

### Requirement: Markdown 解析器实现统一解析器接口

系统 SHALL 实现 `DocumentParser` 抽象接口，声明 `SUPPORTED_TYPES = {"markdown", "md", "txt", "text"}` 和 `RAW_CONTENT_FORMAT = "text"`。

#### Scenario: 支持类型检查

- **WHEN** 调用 `MarkdownParser.supports("markdown")`
- **THEN** 返回 `True`
- **AND** `supports("md")`、`supports("txt")`、`supports("text")` 均返回 `True`

#### Scenario: 大小写不敏感

- **WHEN** 调用 `MarkdownParser.supports("MARKDOWN")` 或 `MarkdownParser.supports("MD")`
- **THEN** 返回 `True`

#### Scenario: 不支持的类型

- **WHEN** 调用 `MarkdownParser.supports("pdf")`
- **THEN** 返回 `False`

### Requirement: 解析完成后清理原始内容

系统 SHALL 在 Markdown 解析完成后从 `doc.metadata` 中移除 `raw_content`。

#### Scenario: 解析完成后清理

- **GIVEN** Markdown 文档以 `metadata.raw_content` 形式提供原始文本
- **WHEN** 调用 `MarkdownParser.parse(doc)` 成功返回
- **THEN** `result.doc.metadata` 中 SHALL 不再包含 `"raw_content"` 键
