# PDF Parsing (Delta)

> Delta for `pdf-parsing`. See `openspec/specs/pdf-parsing/spec.md` for base spec.

## ADDED Requirements

### Requirement: 通过 link rect 与 span bbox 交叉匹配提取超链接锚点

系统 SHALL 将 `page.get_links()` 返回的每个链接的 `from` 矩形与当前页文本 span 的 bbox 做交叉匹配，匹配到的 span 文本作为锚文本，通过 `ParsedElement.link_anchors` 字段记录每个超链接的 URL、锚文本、关联 Asset ID 和位置信息。

#### Scenario: link rect 与 span bbox 交叉匹配成功

- **GIVEN** PDF 页面文本块包含文本 "See docs for details"，其中 "docs" 上有 link rect
- **WHEN** 解析该 PDF 文档
- **THEN** 对应 ParsedElement 的 `link_anchors` 列表包含该链接记录
- **AND** 记录包含 `url`、`text`（匹配到的 span 文本）、`asset_id`、`page`
- **AND** `element.text` 中 span 文本完整保留

#### Scenario: 同一文本块包含多个链接

- **GIVEN** PDF 页面一个文本块包含两个 link rect，分别覆盖不同 URL
- **WHEN** 解析该 PDF 文档
- **THEN** `link_anchors` 包含两条记录
- **AND** 每条记录正确关联对应的 URL
- **AND** `element.asset_ids` 包含两个链接对应的 Asset ID

#### Scenario: link rect 无匹配 span 时回退

- **GIVEN** PDF 页面有一个 link rect，但无法与任何 span bbox 交叉
- **WHEN** 解析该 PDF 文档
- **THEN** 链接的 Asset ID 关联到当前页最后一个非 image 元素
- **AND** `link_anchors` 中 `text` 为空

### Requirement: 识别远程图片 URL 为 image 类型

系统 SHALL 将 URL 后缀为 `.png`、`.jpg`、`.jpeg`、`.gif`、`.webp`、`.bmp`、`.svg` 的远程链接识别为 `AssetType.image`，而非 `AssetType.attachment`。

#### Scenario: 远程图片 URL 创建 image Asset

- **GIVEN** PDF 文本包含 URL `https://cdn.example.com/chart.png`
- **WHEN** 解析该 PDF 文档
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** Asset 的 `mime_type` 为 `image/png`

#### Scenario: 非图片 URL 保持原有分类

- **GIVEN** PDF 包含 `https://example.com/doc.pdf`、`https://youtube.com/watch?v=abc`、`https://example.com/photo.jpg`
- **WHEN** 解析该 PDF 文档
- **THEN** `.pdf` → `attachment`，YouTube → `video`，`.jpg` → `image`

### Requirement: 过滤页眉页脚区域的图片和链接

系统 SHALL 在提取页面图片和超链接时，过滤落在页眉页脚区域（Y 坐标在页面顶部 15% 以内或底部 15% 以内）的资源。

#### Scenario: 页眉区域图片被过滤

- **GIVEN** PDF 页面顶部（Y < 页面高度 × 0.15）包含装饰图片
- **WHEN** 解析该 PDF 文档
- **THEN** 该图片 SHALL NOT 被提取

#### Scenario: 页脚区域链接被过滤

- **GIVEN** PDF 页面底部（Y > 页面高度 × 0.85）包含链接
- **WHEN** 解析该 PDF 文档
- **THEN** 该链接 SHALL NOT 被创建为 Asset

#### Scenario: 正文区域资源正常提取

- **GIVEN** PDF 页面中间区域包含配图和超链接
- **WHEN** 解析该 PDF 文档
- **THEN** 正文区域图片正常提取、链接正常关联

## MODIFIED Requirements

### Requirement: 提取 PDF 中的图片、视频链接和附件资源

系统 SHALL 提取 PDF 内嵌图片并创建 image Asset；识别超链接中的视频 URL、图片 URL 和附件 URL，创建或关联 Asset，并在 ParsedElement 中保留 `asset_ids` 和 `link_anchors`。

#### Scenario: 提取内嵌图片资源

- **GIVEN** PDF 文档第 3 页包含一张内嵌图片
- **WHEN** 解析该 PDF 文档
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** Asset 的 `content_hash` 以 `sha256:` 开头
- **AND** Asset 的 `status` 为 `ready`
- **AND** Asset 的 `original_uri` 包含页面引用信息
- **AND** Asset 保留原始字节数据供后续 MinIO 上传
- **AND** 系统生成 `image` 类型 ParsedElement 并通过 `asset_ids` 引用该 Asset

#### Scenario: 识别超链接中的视频 URL

- **GIVEN** PDF 文档包含指向 `https://example.com/demo.mp4` 的超链接
- **WHEN** 解析该 PDF 文档
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** Asset 的 `original_uri` 为该视频 URL

#### Scenario: 识别超链接中的远程图片 URL

- **GIVEN** PDF 文档包含指向 `https://example.com/screenshot.png` 的超链接
- **WHEN** 解析该 PDF 文档
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** 锚文本记录在所属 ParsedElement 的 `link_anchors` 中

#### Scenario: 识别超链接中的附件 URL

- **GIVEN** PDF 文档包含指向 `https://example.com/manual.pdf` 的超链接
- **WHEN** 解析该 PDF 文档
- **THEN** 系统 SHALL 保留该链接的来源信息
- **AND** 若创建 Asset，则 Asset 的 `asset_type` 为 `attachment`

#### Scenario: 去重相同图片资源

- **GIVEN** 同一 PDF 文档多处使用相同的内嵌图片（相同 content_hash）
- **WHEN** 解析该文档
- **THEN** 系统 SHALL 避免重复创建等价 image Asset
- **AND** 多个 ParsedElement 可以通过 `asset_ids` 引用同一 Asset
