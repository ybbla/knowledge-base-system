## ADDED Requirements

### Requirement: classify_link_text 按链接文字后缀分类
系统 SHALL 提供 `classify_link_text(text)` 工具函数，根据链接文字的后缀名判断资源类型。

#### Scenario: 图片后缀识别为 image_link
- **WHEN** 调用 `classify_link_text("天空.png")` 或 `classify_link_text("photo.jpg")`
- **THEN** 系统 SHALL 返回 `AssetType.image_link`

#### Scenario: 视频后缀识别为 video_link
- **WHEN** 调用 `classify_link_text("演示.mp4")` 或 `classify_link_text("tutorial.mov")`
- **THEN** 系统 SHALL 返回 `AssetType.video_link`

#### Scenario: 文档后缀识别为 document_link
- **WHEN** 调用 `classify_link_text("手册.pdf")` 或 `classify_link_text("报告.docx")`
- **THEN** 系统 SHALL 返回 `AssetType.document_link`

#### Scenario: 无识别后缀返回 web_link
- **WHEN** 调用 `classify_link_text("百度")` 或 `classify_link_text("点击查看")`
- **THEN** 系统 SHALL 返回 `AssetType.web_link`

#### Scenario: 带查询参数的 URL 文本
- **WHEN** 调用 `classify_link_text("file.pdf?version=2")`
- **THEN** 系统 SHALL 正确提取 `.pdf` 后缀并返回 `AssetType.document_link`
