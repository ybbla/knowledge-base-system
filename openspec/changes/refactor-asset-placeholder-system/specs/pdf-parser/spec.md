## MODIFIED Requirements

### Requirement: pdf 解析器适配新 Asset 模型和占位符
pdf 解析器 SHALL 使用新的 Asset 字段语义和 `{{type:n}}` 占位符。

#### Scenario: 嵌入图片 original_uri 为空
- **WHEN** pdf 解析器从页面提取嵌入图片
- **THEN** Asset.original_uri SHALL 为空
- **AND** metadata["filename"] 存储文件名

#### Scenario: 图片占位符格式
- **WHEN** pdf 解析器创建图片元素
- **THEN** 段落文本 SHALL 为 `{{image:N}}` 而非 `[图片: N 页]`

#### Scenario: 超链接按锚文本分类
- **WHEN** pdf 解析器匹配链接到元素
- **THEN** 系统 SHALL 调用 `classify_link_text(anchor_text)` 判断类型
- **AND** 链接文字 SHALL 被 `{{type:N}}` 替换
