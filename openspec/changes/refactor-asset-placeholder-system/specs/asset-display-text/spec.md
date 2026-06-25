## ADDED Requirements

### Requirement: Asset 包含 display_text 字段
Asset 数据模型 SHALL 包含 `display_text` 字段，用于存储链接的显示文字。

#### Scenario: 嵌入资源 display_text 为空
- **WHEN** 解析器创建 asset_type=image 或 asset_type=video 的 Asset
- **THEN** display_text SHALL 为空字符串

#### Scenario: 链接资源 display_text 存储锚文本
- **WHEN** 解析器创建 asset_type 为 image_link/video_link/document_link/web_link 的 Asset
- **THEN** display_text SHALL 存储超链接的显示文字
- **AND** 示例：链接文字 "天空.png" → display_text="天空.png"

### Requirement: 嵌入资源 original_uri 为空
asset_type 为 image 或 video 的 Asset SHALL 设置 original_uri 为空字符串。

#### Scenario: docx 嵌入图片 original_uri 为空
- **WHEN** docx 解析器从 word/media/ 提取嵌入图片
- **THEN** Asset.original_uri SHALL 为空字符串
- **AND** 文件名存储在 metadata["filename"] 中

### Requirement: 链接资源 original_uri 存储 URL
asset_type 为 image_link/video_link/document_link/web_link 的 Asset SHALL 在 original_uri 中存储原始 HTTP URL。

#### Scenario: 超链接 original_uri 存储 URL
- **WHEN** 解析器遇到 w:hyperlink 指向 https://example.com/file.pdf
- **THEN** Asset.original_uri SHALL 为 "https://example.com/file.pdf"
