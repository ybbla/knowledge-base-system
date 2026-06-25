## MODIFIED Requirements

### Requirement: docx 解析器适配新 Asset 模型
docx 解析器 SHALL 使用新的 Asset 字段语义创建资源，使用统一的 `{{type:n}}` 占位符。

#### Scenario: 嵌入图片创建 Asset
- **WHEN** `_build_image_asset_map` 从 word/media/ 提取嵌入图片
- **THEN** Asset.original_uri SHALL 为空
- **AND** Asset.display_text SHALL 为空
- **AND** metadata["filename"] 存储原始文件名
- **AND** `_data` 运行时注入字节数据

#### Scenario: 嵌入视频创建 Asset
- **WHEN** `_build_image_asset_map` 提取到 .mov/.mp4 等视频文件
- **THEN** Asset.asset_type SHALL 为 video
- **AND** 其余字段与嵌入图片规则一致

#### Scenario: 超链接分类改为按链接文字后缀
- **WHEN** `_process_paragraph` 处理 w:hyperlink
- **THEN** 系统 SHALL 调用 `classify_link_text(link_text)` 而非 `_classify_link_url(url)`
- **AND** 根据返回值设置 asset_type

#### Scenario: 超链接文字被占位符替换
- **WHEN** w:hyperlink 的链接文字为 "天空.png"
- **THEN** 段落 text_parts SHALL 追加 `{{image:N}}` 而非 "天空.png"
- **AND** Asset.display_text SHALL 存储 "天空.png"

#### Scenario: 字段指令文字被占位符替换
- **WHEN** w:instrText 包含 WeDrive 嵌入文件 `\tdfn xxx.mov`
- **THEN** 段落文本 SHALL 仅包含 `{{video:N}}`，不保留文件名
- **AND** Asset.display_text 存储 `\tdfn` 中的文件名

#### Scenario: 内联图片占位符不含文字前缀
- **WHEN** w:drawing 指向嵌入图片
- **THEN** 段落 text_parts SHALL 追加 `{{image:N}}` 而非 `[图片: filename]{{image:N}}`

#### Scenario: 删除 _extract_videos
- **WHEN** docx 解析流程执行
- **THEN** 不 SHALL 调用 `_extract_videos` 后处理
- **AND** 视频链接已在 w:hyperlink 处理阶段完成

### Requirement: docx 表格处理适配新占位符
`_process_table` SHALL 使用与 `_process_paragraph` 一致的占位符和 Asset 创建逻辑。

#### Scenario: 表格内嵌图片
- **WHEN** 表格单元格包含 w:drawing
- **THEN** 单元格文本 SHALL 追加 `{{image:N}}`

#### Scenario: 表格内超链接
- **WHEN** 表格单元格包含 w:hyperlink
- **THEN** 链接文字 SHALL 被 `{{type:N}}` 替换
