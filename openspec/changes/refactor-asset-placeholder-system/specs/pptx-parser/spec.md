## MODIFIED Requirements

### Requirement: pptx 解析器适配新占位符
pptx 解析器 SHALL 使用 `{{type:n}}` 格式占位符。

#### Scenario: 图片占位符
- **WHEN** pptx 解析器提取幻灯片中的图片
- **THEN** 系统 SHALL 生成 `{{image:N}}` 占位符
- **AND** 不再生成 `[图片: filename]` 格式

#### Scenario: 嵌入图片 original_uri 为空
- **WHEN** pptx 解析器从 pptx zip 中提取嵌入图片
- **THEN** Asset.original_uri SHALL 为空
- **AND** metadata["filename"] 存储文件名
