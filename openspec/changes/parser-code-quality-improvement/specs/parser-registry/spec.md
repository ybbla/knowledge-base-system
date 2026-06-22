# Parser Registry (Delta)

## ADDED Requirements

### Requirement: 支持注销已注册的解析器

系统 SHALL 支持通过 `ParserRegistry.unregister(source_type)` 方法移除指定的解析器注册项。

#### Scenario: 注销后不再匹配

- **GIVEN** 注册表中已注册 `"pdf"` 对应的解析器
- **WHEN** 调用 `registry.unregister("pdf")`
- **THEN** 后续 `registry.get("pdf")` 抛出 `UnsupportedFormatError`
- **AND** 注册表中不再包含 `"pdf"` 类型

#### Scenario: 注销未注册的类型不报错

- **GIVEN** 注册表中不存在 `"epub"` 对应的解析器
- **WHEN** 调用 `registry.unregister("epub")`
- **THEN** 操作静默成功（幂等），不抛出异常

### Requirement: 支持解析器优先级

系统 SHALL 支持在注册解析器时指定 `priority` 参数（整数，默认 0），值越大优先级越高。相同 `source_type` 的高优先级解析器覆盖低优先级。

#### Scenario: 高优先级覆盖低优先级

- **GIVEN** 注册表已注册优先级为 0 的 `PdfParser`
- **WHEN** 注册优先级为 10 的自定义 `CustomPdfParser`（同样声明 `SUPPORTED_TYPES={"pdf"}`）
- **THEN** `registry.get("pdf")` 返回 `CustomPdfParser` 实例
- **AND** 记录 WARNING 日志说明覆盖发生

#### Scenario: 低优先级不覆盖高优先级

- **GIVEN** 注册表已注册优先级为 10 的 `PdfParser`
- **WHEN** 注册优先级为 5 的另一个解析器（同样声明 `"pdf"`）
- **THEN** `registry.get("pdf")` 仍返回优先级为 10 的 `PdfParser` 实例
- **AND** 记录 WARNING 日志说明跳过低优先级注册

## MODIFIED Requirements

### Requirement: 注册多个解析器并按 source_type 分派

系统 SHALL 维护一个解析器注册表，支持注册多个 `DocumentParser` 实现，并根据 `source_type` 返回匹配的解析器。

#### Scenario: 注册 MarkdownParser、DocxParser、XlsxParser、HtmlParser 和 PptxParser

- **WHEN** 向注册表注册 `MarkdownParser`（`SUPPORTED_TYPES={"markdown", "md", "txt", "text"}`）、`DocxParser`（`SUPPORTED_TYPES={"docx"}`）、`XlsxParser`（`SUPPORTED_TYPES={"xlsx"}`）、`HtmlParser`（`SUPPORTED_TYPES={"html", "htm"}`）和 `PptxParser`（`SUPPORTED_TYPES={"pptx"}`）
- **THEN** `registry.get("markdown")` 返回 MarkdownParser 实例
- **AND** `registry.get("docx")` 返回 DocxParser 实例
- **AND** `registry.get("xlsx")` 返回 XlsxParser 实例
- **AND** `registry.get("html")` 和 `registry.get("htm")` 返回 HtmlParser 实例
- **AND** `registry.get("pptx")` 返回 PptxParser 实例
- **AND** `registry.get("MD")`、`registry.get("XLSX")`、`registry.get("HTML")` 和 `registry.get("PPTX")` 大小写不敏感返回对应解析器实例

#### Scenario: 未注册的 source_type

- **WHEN** 调用 `registry.get("epub")` 但未注册 EPUB 解析器
- **THEN** 抛出明确错误，提示 "Unsupported source_type: epub"，且错误信息列出已注册的 source_type

#### Scenario: 重复注册覆盖

- **WHEN** 向注册表注册两个均声明支持 `"markdown"` 且优先级相同的解析器
- **THEN** 后注册的解析器覆盖先前的，且记录 WARNING 日志
