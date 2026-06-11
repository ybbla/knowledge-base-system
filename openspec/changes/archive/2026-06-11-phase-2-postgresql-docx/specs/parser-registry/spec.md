# Parser Registry

## Purpose

提供解析器注册与自动选择机制，使入库管线根据 Document 的 `source_type` 自动匹配对应解析器，消除硬编码的单一解析器依赖。

## ADDED Requirements

### Requirement: 注册多个解析器并按 source_type 分派

系统 SHALL 维护一个解析器注册表，支持注册多个 `DocumentParser` 实现，并根据 `source_type` 返回匹配的解析器。

#### Scenario: 注册 MarkdownParser 和 DocxParser

- **WHEN** 向注册表注册 `MarkdownParser`（`SUPPORTED_TYPES={"markdown", "md", "txt", "text"}`）和 `DocxParser`（`SUPPORTED_TYPES={"docx"}`）
- **THEN** `registry.get("markdown")` 返回 MarkdownParser 实例
- **AND** `registry.get("docx")` 返回 DocxParser 实例
- **AND** `registry.get("MD")` 大小写不敏感返回 MarkdownParser 实例

#### Scenario: 未注册的 source_type

- **WHEN** 调用 `registry.get("pdf")` 但未注册 PDF 解析器
- **THEN** 抛出明确错误，提示 "Unsupported source_type: pdf"，且错误信息列出已注册的 source_type

#### Scenario: 重复注册覆盖

- **WHEN** 向注册表注册两个均声明支持 `"markdown"` 的解析器
- **THEN** 后注册的解析器覆盖先前的，且记录 WARNING 日志

### Requirement: 入库管线使用注册表选择解析器

系统 SHALL 在 `IngestionPipeline` 中通过注册表而非硬编码解析器来解析文档。

#### Scenario: 根据 source_type 自动选择解析器

- **WHEN** 提交 `source_type="docx"` 的文档入库
- **THEN** 管线通过注册表获取 DocxParser 并执行解析
- **AND** 提交 `source_type="markdown"` 的文档时使用 MarkdownParser

#### Scenario: 无匹配解析器时返回错误

- **WHEN** 提交 `source_type="pdf"` 的文档入库，但 PDF 解析器未注册
- **THEN** 入库 job 状态变为 `failed`，错误信息包含 "Unsupported source_type"
