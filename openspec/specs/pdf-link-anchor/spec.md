# PDF Link Anchor

## Purpose

定义 PDF 文档中超链接锚点的提取能力：通过 `page.get_links()` 获取链接矩形，与文本 span 的 bbox 做交叉匹配来确定锚文本（覆盖在链接上的文字），保留锚文本于 element.text 中，并通过 `ParsedElement.link_anchors` 字段记录链接的 URL、锚文本、关联 Asset ID 和位置信息。

> 技术验证结论：PyMuPDF 1.27.2 的 span 字典中不存在 `uri` 字段，因此锚文本提取采用 link rect 与 span bbox 交叉匹配的方案。

## Requirements

### Requirement: 通过 link rect 与 span bbox 交叉匹配提取锚文本

系统 SHALL 在解析 PDF 时，将 `page.get_links()` 返回的每个链接的 `from` 矩形与当前页所有文本 span 的 bbox 做交叉匹配（取交集面积占 span 面积比率 ≥ 0.1 的 span），匹配到的 span 文本即为链接的锚文本。

#### Scenario: 链接矩形与 span 精确匹配

- **GIVEN** PDF 页面包含文本 "See https://docs.example.com/manual.pdf for details"，其中 URL 部分有 link rect 覆盖
- **WHEN** 解析该 PDF 文档
- **THEN** 系统通过 link rect 与 span bbox 交叉匹配找到对应 span
- **AND** 对应的 ParsedElement 的 `link_anchors` 包含该链接记录
- **AND** 记录的 `text` 为 span 的完整文本（"See https://docs.example.com/manual.pdf for details"）
- **AND** `element.text` 中该文本完整保留

#### Scenario: 同一页面多个链接均正确匹配

- **GIVEN** PDF 页面包含两个文本块，分别带有指向 `https://a.example.com` 和 `https://b.example.com` 的超链接
- **WHEN** 解析该 PDF 文档
- **THEN** 两个链接的 asset_id 分别关联到各自匹配的文本块对应的 ParsedElement
- **AND** 两个链接不关联到同一个元素

#### Scenario: 无匹配 span 时兜底关联

- **GIVEN** PDF 页面包含一个超链接，但其 link rect 无法与任何 span bbox 交叉匹配
- **WHEN** 解析该 PDF 文档
- **THEN** 系统 SHALL 将该链接关联到当前页最后一个非 image 元素
- **AND** `link_anchors` 中 `text` 字段为空字符串

### Requirement: 超链接的 Asset 类型正确识别

系统 SHALL 根据链接 URL 的后缀和模式正确分类 Asset 类型：视频链接 → `AssetType.video`，图片链接 → `AssetType.image`，文档附件链接 → `AssetType.attachment`。

#### Scenario: 附件 PDF 链接归类为 attachment

- **GIVEN** PDF 文本中链接指向 `https://example.com/report.pdf`
- **WHEN** 解析该 PDF 文档
- **THEN** 系统为该链接创建 `asset_type="attachment"` 的 Asset

#### Scenario: 远程图片链接归类为 image

- **GIVEN** PDF 文本中链接指向 `https://cdn.example.com/chart.png`
- **WHEN** 解析该 PDF 文档
- **THEN** 系统为该链接创建 `asset_type="image"` 的 Asset

### Requirement: 链接锚文本保留在元素文本中

系统 SHALL 确保链接上的锚文本（匹配到的 span 文本）完整保留在 `ParsedElement.text` 中，不因链接提取而被移除或替换。

#### Scenario: 锚文本在 element.text 中完整保留

- **GIVEN** PDF 文本 "点击这里下载"，link rect 覆盖 "这里" 所在 span
- **WHEN** 解析该 PDF 文档
- **THEN** `element.text` 包含该 span 的完整文本
- **AND** `link_anchors` 中 `text` 为匹配到的 span 文本
