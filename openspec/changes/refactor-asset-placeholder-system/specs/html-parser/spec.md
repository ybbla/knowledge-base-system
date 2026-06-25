## MODIFIED Requirements

### Requirement: html 解析器适配新占位符
html 解析器 SHALL 使用 `{{type:n}}` 格式占位符。

#### Scenario: 图片占位符
- **WHEN** 解析 `<img alt="photo" src="url">` 标签
- **THEN** 系统 SHALL 生成 `{{image:N}}` 占位符
- **AND** 不再生成 `[图片: alt]` 格式

#### Scenario: 视频占位符
- **WHEN** 解析 `<video src="url">` 标签
- **THEN** 系统 SHALL 生成 `{{video:N}}` 占位符

#### Scenario: 超链接分类
- **WHEN** 解析 `<a href="url">text</a>` 标签
- **THEN** 系统 SHALL 调用 `classify_link_text(text)` 判断类型
- **AND** 链接文字 SHALL 被 `{{type:N}}` 替换
