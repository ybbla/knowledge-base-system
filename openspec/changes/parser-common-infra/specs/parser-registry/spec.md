# Parser Registry (Delta)

## ADDED Requirements

### Requirement: 支持注销已注册的解析器

系统 SHALL 支持通过 `ParserRegistry.unregister(source_type)` 方法移除指定的解析器注册项。

#### Scenario: 注销后不再匹配

- **GIVEN** 注册表中已注册 `"pdf"` 对应的解析器
- **WHEN** 调用 `registry.unregister("pdf")`
- **THEN** 后续 `registry.get("pdf")` 抛出 `UnsupportedFormatError`

#### Scenario: 注销未注册的类型不报错

- **GIVEN** 注册表中不存在 `"epub"` 对应的解析器
- **WHEN** 调用 `registry.unregister("epub")`
- **THEN** 操作静默成功，不抛出异常

### Requirement: 支持解析器优先级

系统 SHALL 支持在注册解析器时指定 `priority` 参数（整数，默认 0），值越大优先级越高。相同 `source_type` 的高优先级解析器覆盖低优先级。

#### Scenario: 高优先级覆盖低优先级

- **GIVEN** 注册表已注册优先级为 0 的解析器
- **WHEN** 注册优先级为 10 的同类型解析器
- **THEN** `registry.get()` 返回高优先级解析器实例
- **AND** 记录 WARNING 日志

#### Scenario: 低优先级不覆盖高优先级

- **GIVEN** 注册表已注册优先级为 10 的解析器
- **WHEN** 注册优先级为 5 的同类型解析器
- **THEN** `registry.get()` 仍返回优先级为 10 的解析器

### Requirement: 支持全量查询已注册类型

系统 SHALL 提供 `ParserRegistry.get_all()` 方法返回所有已注册的 `{source_type: DocumentParser}` 映射。

#### Scenario: 查询所有注册项

- **GIVEN** 注册表已注册 `"markdown"` 和 `"docx"` 两个类型
- **WHEN** 调用 `registry.get_all()`
- **THEN** 返回 `{"markdown": MarkdownParser实例, "docx": DocxParser实例}`

## MODIFIED Requirements

### Requirement: 注册多个解析器并按 source_type 分派

系统 SHALL 维护一个解析器注册表，支持注册多个 `DocumentParser` 实现，并根据 `source_type` 返回匹配的解析器。

#### Scenario: 注册 MarkdownParser 和 DocxParser

- **WHEN** 向注册表注册 `MarkdownParser`（`SUPPORTED_TYPES={"markdown", "md", "txt", "text"}`）和 `DocxParser`（`SUPPORTED_TYPES={"docx"}`）
- **THEN** `registry.get("markdown")` 返回 MarkdownParser 实例
- **AND** `registry.get("MD")` 大小写不敏感返回 MarkdownParser 实例

#### Scenario: 未注册的 source_type

- **WHEN** 调用 `registry.get("epub")` 但未注册对应解析器
- **THEN** 抛出 `UnsupportedFormatError`，错误信息列出已注册的 source_type

#### Scenario: 重复注册覆盖

- **WHEN** 向注册表注册两个均声明支持 `"markdown"` 且优先级相同的解析器
- **THEN** 后注册的解析器覆盖先前的，且记录 WARNING 日志
