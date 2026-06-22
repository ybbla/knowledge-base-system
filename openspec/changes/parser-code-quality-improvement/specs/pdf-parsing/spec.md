# PDF Parsing (Delta)

## MODIFIED Requirements

### Requirement: 提取 PDF 中的图片、视频链接和附件资源

系统 SHALL 提取 PDF 内嵌图片并创建 image Asset；识别超链接中的视频 URL 和附件 URL，创建或关联 Asset，并在 ParsedElement 中保留 `asset_ids`。

#### Scenario: 提取内嵌图片资源

- **GIVEN** PDF 文档第 3 页包含一张内嵌图片
- **WHEN** 解析该 PDF 文档
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** Asset 的 `content_hash` 以 `sha256:` 开头
- **AND** Asset 的 `status` 为 `pending`
- **AND** Asset 的 `original_uri` 包含页面引用信息
- **AND** Asset 保留原始字节数据供后续 MinIO 上传
- **AND** 系统生成 `image` 类型 ParsedElement 并通过 `asset_ids` 引用该 Asset
- **AND** ParsedElement 的 `source_location.page` 为图片所在页码

#### Scenario: 识别超链接中的视频 URL

- **GIVEN** PDF 文档包含指向 `https://example.com/demo.mp4` 的超链接
- **WHEN** 解析该 PDF 文档
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** Asset 的 `original_uri` 为该视频 URL
- **AND** Asset 的 `status` 为 `pending`
- **AND** 阶段 4 不下载或理解视频内容

#### Scenario: 识别超链接中的附件 URL

- **GIVEN** PDF 文档包含指向 `https://example.com/manual.pdf` 的超链接
- **WHEN** 解析该 PDF 文档
- **THEN** 系统 SHALL 保留该链接的来源信息
- **AND** 若创建 Asset，则 Asset 的 `asset_type` 为 `attachment`
- **AND** 阶段 4 不下载或递归解析该附件

#### Scenario: 去重相同图片资源

- **GIVEN** 同一 PDF 文档多处使用相同的内嵌图片（相同 content_hash）
- **WHEN** 解析该文档
- **THEN** 系统 SHALL 避免重复创建等价 image Asset
- **AND** 多个 ParsedElement 可以通过 `asset_ids` 引用同一 Asset

#### Scenario: 解析完成后清理原始内容

- **GIVEN** PDF 文档以 `metadata.raw_content` 形式提供原始字节
- **WHEN** 调用 `PdfParser.parse(doc)` 成功返回
- **THEN** `result.doc.metadata` 中 SHALL 不再包含 `"raw_content"` 键
- **AND** 解析结果不受影响

## ADDED Requirements

### Requirement: 扫描件 PDF 降级处理

系统 SHALL 在扫描件 PDF（仅含图片、无可提取文本层）时降级处理，标记 `needs_ocr` 而非抛出异常阻塞入库。

#### Scenario: 扫描件 PDF 标记为需要 OCR

- **GIVEN** 一个 PDF 文档有页面但所有页面均为图片，无可提取文本层
- **WHEN** 解析该 PDF 文档
- **THEN** 解析成功返回，而非抛出 `ValueError`
- **AND** `result.doc.metadata` 中 `"needs_ocr"` 设为 `true`
- **AND** 内嵌图片作为 image Asset 保留
- **AND** 至少生成一个 `unknown` 类型 ParsedElement 说明"文档为扫描件，需要 OCR 处理"

#### Scenario: 完全无内容的 PDF 仍报错

- **GIVEN** 一个 PDF 文档既无文本也无图片
- **WHEN** 解析该 PDF 文档
- **THEN** 入库 job 状态变为 `failed`
- **AND** 错误信息包含 PDF 解析失败原因
