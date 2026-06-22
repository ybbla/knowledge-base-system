# PPTX Parsing (Delta)

## MODIFIED Requirements

### Requirement: 解析 PPTX 文本、标题和列表

系统 SHALL 将 PPTX 中的标题、文本框、正文占位符和项目符号列表解析为统一 ParsedElement，保留可追溯来源和稳定顺序。

#### Scenario: 解析标题占位符

- **GIVEN** 一张幻灯片包含标题占位符
- **WHEN** 解析该幻灯片
- **THEN** 系统生成 `title` 类型 ParsedElement
- **AND** `title.text` 为标题文本
- **AND** `source_location.section_path` 包含该标题文本
- **AND** metadata 记录 `heading_level=1`、`slide_index` 和形状来源信息

#### Scenario: 解析普通文本框

- **GIVEN** 一张幻灯片包含普通文本框
- **WHEN** 解析该文本框
- **THEN** 系统生成 `paragraph` 类型 ParsedElement
- **AND** `text` 为去除多余空白后的可读文本（换行符统一归一化为空格）
- **AND** metadata 记录 `shape_id`、`shape_name`、`left`、`top`、`width` 和 `height`

#### Scenario: 解析项目符号列表

- **GIVEN** 一张幻灯片包含多条有明确缩进层级差异的项目符号正文
- **WHEN** 解析该文本形状
- **THEN** 系统生成 `list` 类型容器元素
- **AND** 每条项目符号生成归属于该容器的 `paragraph` 子元素
- **AND** 子元素 metadata 记录项目符号层级或缩进信息

#### Scenario: BODY 占位符不自动判定为列表

- **GIVEN** 一张幻灯片的 BODY 占位符包含 3 个段落，均无缩进层级差异
- **WHEN** 解析该文本形状
- **THEN** 系统 SHALL 生成 `paragraph` 类型 ParsedElement（非 `list` 类型）
- **AND** 仅当段落间存在缩进层级差异（`level > 0`）或明确列表标记时才判定为列表

#### Scenario: 稳定生成阅读顺序

- **GIVEN** 同一幻灯片上存在多个文本形状
- **WHEN** 解析该幻灯片
- **THEN** 系统 SHALL 按 `top`、`left` 和原始形状索引生成稳定 `sequence_order`
- **AND** 不因 OOXML 内部顺序变化导致同一视觉布局下的解析顺序随机变化

## ADDED Requirements

### Requirement: 解析完成后清理原始内容

系统 SHALL 在 PPTX 解析完成后从 `doc.metadata` 中移除 `raw_content`。

#### Scenario: 解析完成后清理

- **GIVEN** PPTX 文档以 `metadata.raw_content` 形式提供原始字节
- **WHEN** 调用 `PptxParser.parse(doc)` 成功返回
- **THEN** `result.doc.metadata` 中 SHALL 不再包含 `"raw_content"` 键
