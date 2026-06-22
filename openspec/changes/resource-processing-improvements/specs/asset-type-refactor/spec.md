# Asset Type Refactor

## Purpose

重构 `AssetType` 枚举，将四种语义模糊的类型（image/video/audio/attachment）替换为四种语义明确的类型（image/image_link/video_link/document_link）。

## ADDED Requirements

### Requirement: AssetType 枚举定义

系统 SHALL 使用以下四种 AssetType 枚举值：

- `image`：内嵌图片，解析器提供了实际字节数据（`_data` 不为空）
- `image_link`：外部图片链接，仅有 URL 引用，需下载
- `video_link`：视频链接，仅有 URL 引用，需下载
- `document_link`：文档链接，仅有 URL 引用，需下载后触发子文档入库流水线

#### Scenario: 解析器按场景产出正确类型

- **WHEN** 解析器提取到内嵌图片字节（如 DOCX 内嵌图片、PDF 渲染图片）
- **THEN** 创建 `asset_type=image` 的 Asset

#### Scenario: 解析器识别图片链接

- **WHEN** 解析器识别到外部图片 URL（如 HTML `<img src="https://...">`、Markdown `![](url)`）
- **THEN** 创建 `asset_type=image_link` 的 Asset

#### Scenario: 解析器识别视频链接

- **WHEN** 解析器识别到视频 URL（如 HTML `<video>`、`<iframe>` 视频平台链接）
- **THEN** 创建 `asset_type=video_link` 的 Asset

#### Scenario: 解析器识别文档链接

- **WHEN** 解析器识别到文档 URL（如 HTML `<a href=".pdf">`、Markdown `[text](url)`）
- **THEN** 创建 `asset_type=document_link` 的 Asset

### Requirement: 删除旧枚举值

系统 SHALL 移除 `AssetType.audio` 和 `AssetType.attachment`。

#### Scenario: audio 归入 video_link

- **WHEN** PPTX 解析器识别到音频链接
- **THEN** 创建 `asset_type=video_link` 的 Asset

#### Scenario: attachment 归入 document_link

- **WHEN** 解析器识别到无法明确归类的文档/附件链接
- **THEN** 创建 `asset_type=document_link` 的 Asset

### Requirement: 删除关联死字段

系统 SHALL 移除 `ElementType.embedded_document` 枚举值和 `ParsedElement.embedded_doc_id` 字段。

#### Scenario: embedded_document 元素类型不再存在

- **WHEN** 代码中引用 `ElementType.embedded_document`
- **THEN** 该引用不再有效，改为创建 `document_link` Asset 处理子文档

#### Scenario: ParsedElement 不再有 embedded_doc_id

- **WHEN** 创建 ParsedElement 实例
- **THEN** 不再设置 `embedded_doc_id` 字段
