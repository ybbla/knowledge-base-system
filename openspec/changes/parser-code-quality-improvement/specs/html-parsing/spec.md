# HTML Parsing (Delta)

## MODIFIED Requirements

### Requirement: 将 HTML 正文结构解析为元素

系统 SHALL 将 HTML 正文中的段落、引用块、列表和代码块解析为统一 ParsedElement，保留文档顺序和来源上下文。

#### Scenario: 解析段落和引用块

- **GIVEN** HTML 文档在正文中包含 `p` 和 `blockquote`
- **WHEN** 解析该 HTML 文档
- **THEN** 系统生成 `paragraph` 类型 ParsedElement
- **AND** 段落文本为去除多余空白后的可读文本
- **AND** `source_location.section_path` 使用最近标题路径
- **AND** 系统 SHALL 直接从 DOM 树提取文本，不进行序列化重解析

#### Scenario: 解析有序和无序列表

- **GIVEN** HTML 文档包含 `ul` 和 `ol` 列表
- **WHEN** 解析该 HTML 文档
- **THEN** 系统生成 `list` 类型容器元素
- **AND** 每个列表项生成归属于该容器的 `paragraph` 子元素
- **AND** 列表容器 metadata 记录 `ordered=true` 或 `ordered=false`

#### Scenario: 解析代码块

- **GIVEN** HTML 文档包含 `pre` 或 `code` 代码块
- **WHEN** 解析该 HTML 文档
- **THEN** 系统生成 `code` 类型 ParsedElement
- **AND** `text` 保留代码文本
- **AND** 若能从 class 或 language 标记识别语言，则写入 `metadata.language`

#### Scenario: 深层嵌套 HTML 不栈溢出

- **GIVEN** HTML 文档包含超过 500 层嵌套的 `<div>` 标签
- **WHEN** 解析该 HTML 文档
- **THEN** 系统 SHALL 在达到递归深度上限（默认 256）时安全截断
- **AND** 已解析的上层内容正常返回
- **AND** 不抛出 `RecursionError`

## ADDED Requirements

### Requirement: 解析完成后清理原始内容

系统 SHALL 在 HTML 解析完成后从 `doc.metadata` 中移除 `raw_content`。

#### Scenario: 解析完成后清理

- **GIVEN** HTML 文档以 `metadata.raw_content` 形式提供原始文本
- **WHEN** 调用 `HtmlParser.parse(doc)` 成功返回
- **THEN** `result.doc.metadata` 中 SHALL 不再包含 `"raw_content"` 键
- **AND** 解析结果不受影响
