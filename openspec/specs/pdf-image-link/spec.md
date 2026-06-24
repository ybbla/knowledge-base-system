# PDF Image Link

## Purpose

定义 PDF 文档中远程图片 URL 的识别能力：将指向远程图片文件（如 `https://...screenshot.png`）的超链接或文本 URL 归类为 `AssetType.image`，而非 `AssetType.attachment`，确保下游 `process_image()` 能正确处理这些图片资源。

## Requirements

### Requirement: 识别远程图片 URL

系统 SHALL 在解析 PDF 中的 URL 时，通过文件后缀名识别指向远程图片的链接（`.png`、`.jpg`、`.jpeg`、`.gif`、`.webp`、`.bmp`、`.svg`），将其 Asset 类型设为 `AssetType.image`。

#### Scenario: 远程 PNG 图片被识别为 image 类型

- **GIVEN** PDF 文档包含文本中的 URL `https://cdn.example.com/screenshot.png`
- **WHEN** 解析该 PDF 文档
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** Asset 的 `original_uri` 为该图片 URL

#### Scenario: 远程 JPEG 图片被识别为 image 类型

- **GIVEN** PDF 文档包含超链接 `https://example.com/photo.jpg`
- **WHEN** 解析该 PDF 文档
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** Asset 的 `mime_type` 为 `image/jpeg`

#### Scenario: 非图片 URL 保持原有分类

- **GIVEN** PDF 文档包含 URL `https://example.com/document.pdf` 和 `https://youtube.com/watch?v=abc`
- **WHEN** 解析该 PDF 文档
- **THEN** `.pdf` 链接的 Asset 类型为 `attachment`
- **AND** YouTube 链接的 Asset 类型为 `video`

#### Scenario: 无后缀图片 URL 不误判

- **GIVEN** PDF 文档包含 URL `https://example.com/images/photo`（无文件后缀）
- **WHEN** 解析该 PDF 文档
- **THEN** 系统 SHALL 不将其识别为 `image` 类型
- **AND** 按默认规则归类为 `attachment` 类型

### Requirement: 远程图片资源进入处理管线

系统 SHALL 确保被识别为 `AssetType.image` 的远程图片 URL Asset 能进入 `process_image()` 处理管线，由 `read_uri_bytes()` 通过 HTTP GET 下载图片字节并进行视觉理解。

#### Scenario: 远程图片被 process_image 处理

- **GIVEN** PDF 解析产出了一个 `asset_type="image"`、`original_uri` 为远程 HTTP URL 的 Asset
- **WHEN** 入库管线调用 `_prepare_assets()`
- **THEN** `process_image()` SHALL 通过 `read_uri_bytes()` 下载该图片
- **AND** 下载成功时进行魔数校验和视觉理解
