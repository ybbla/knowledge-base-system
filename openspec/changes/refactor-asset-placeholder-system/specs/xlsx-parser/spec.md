## MODIFIED Requirements

### Requirement: xlsx 解析器适配新占位符
xlsx 解析器 SHALL 使用 `{{type:n}}` 格式占位符。

#### Scenario: 图片占位符
- **WHEN** xlsx 解析器提取嵌入图片
- **THEN** 系统 SHALL 生成 `{{image:N}}` 占位符
- **AND** placeholder 字段不为空

#### Scenario: 嵌入图片 original_uri 为空
- **WHEN** xlsx 解析器从 xlsx zip 中提取嵌入图片
- **THEN** Asset.original_uri SHALL 为空
