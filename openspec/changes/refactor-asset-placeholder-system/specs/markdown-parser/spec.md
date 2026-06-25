## MODIFIED Requirements

### Requirement: markdown 解析器适配新占位符
markdown 解析器 SHALL 使用 `{{type:n}}` 格式占位符，链接文字被占位符替换。

#### Scenario: 嵌入图片占位符
- **WHEN** 解析 `![alt](url)` 语法
- **THEN** 系统 SHALL 生成 `{{image:N}}` 占位符
- **AND** Asset.display_text 为空

#### Scenario: 链接文字被替换
- **WHEN** 解析 `[photo.jpg](https://example.com/abc)` 语法
- **THEN** 系统 SHALL 调用 `classify_link_text("photo.jpg")` 判断类型
- **AND** 段落文本 SHALL 为 `{{image:N}}` 而非 `photo.jpg`
- **AND** Asset.display_text="photo.jpg"

#### Scenario: placeholder_for 格式变更
- **WHEN** 调用 `placeholder_for("image")`
- **THEN** 系统 SHALL 返回 `{{image:1}}` `{{image:2}}` 格式

#### Scenario: web_link 类型链接
- **WHEN** 解析 `[百度](https://baidu.com)` 语法
- **THEN** classify_link_text("百度") 返回 web_link
- **AND** 段落文本 SHALL 为 `{{web:N}}`
- **AND** Asset.display_text="百度"
