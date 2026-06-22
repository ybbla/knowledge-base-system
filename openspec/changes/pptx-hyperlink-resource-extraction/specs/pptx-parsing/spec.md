## MODIFIED Requirements

### Requirement: 识别 PPTX 图片、视频和附件资源

系统 SHALL 识别 PPTX 中可追溯的图片、视频 URL、音频 URL、附件和外部链接资源，创建或关联 Asset，在 ParsedElement 中保留 `asset_ids`，并 SHALL 在 `structured_data.links` 中记录每个超链接的文字、URL 和类型信息。

#### Scenario: 提取内嵌图片资源

- **GIVEN** PPTX 幻灯片包含内嵌图片
- **WHEN** 解析该图片形状
- **THEN** 系统创建 `asset_type="image"` 的 Asset
- **AND** Asset 的 `status` 为 `ready`
- **AND** Asset 保留 MIME 类型、内容 hash 和原始字节
- **AND** 系统生成 `image` 类型 ParsedElement 并通过 `asset_ids` 引用该 Asset

#### Scenario: 识别文本中的视频 URL

- **GIVEN** PPTX 文本框包含 `https://example.com/demo.mp4`
- **WHEN** 解析该文本框
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** Asset 的 `original_uri` 为该视频 URL
- **AND** Asset 的 `status` 为 `ready`
- **AND** 阶段 4 不下载或理解视频内容

#### Scenario: 识别文本中的音频 URL

- **GIVEN** PPTX 文本框包含 `https://example.com/audio.mp3`
- **WHEN** 解析该文本框
- **THEN** 系统创建 `asset_type="audio"` 的 Asset
- **AND** Asset 的 `original_uri` 为该音频 URL
- **AND** Asset 的 `status` 为 `ready`

#### Scenario: 识别附件或外部文件链接

- **GIVEN** PPTX 形状超链接指向 `https://example.com/manual.pdf`
- **WHEN** 解析该形状
- **THEN** 系统 SHALL 保留该链接的来源信息
- **AND** 若创建 Asset，则 Asset 的 `asset_type` 为 `attachment`
- **AND** 阶段 4 不下载或递归解析该附件

#### Scenario: 去重同一文档内重复资源

- **GIVEN** 同一 PPTX 文档多处引用相同外部 URL 或相同媒体内容
- **WHEN** 解析该文档
- **THEN** 系统 SHALL 避免重复创建等价 Asset
- **AND** 多个 ParsedElement 可以通过 `asset_ids` 引用同一 Asset

#### Scenario: 保留文本运行中的超链接文字

- **GIVEN** PPTX 文本框中有一段文字"点击查看文档"设置了超链接指向 `https://example.com/doc.pdf`
- **WHEN** 解析该文本框
- **THEN** 生成的 ParsedElement 的 `text` SHALL 包含"点击查看文档"这段文字
- **AND** `structured_data.links` SHALL 包含条目 `{"text": "点击查看文档", "url": "https://example.com/doc.pdf", "link_type": "document"}`
- **AND** 系统创建 `asset_type="attachment"` 的 Asset 并通过 `asset_ids` 引用

#### Scenario: 保留形状级超链接的文字

- **GIVEN** PPTX 文本形状设置了 `click_action.hyperlink.address` 指向 `https://example.com/video.mp4`，形状文本为"观看演示"
- **WHEN** 解析该形状
- **THEN** `structured_data.links` SHALL 包含条目 `{"text": "观看演示", "url": "https://example.com/video.mp4", "link_type": "video"}`
- **AND** 系统创建 `asset_type="video"` 的 Asset

#### Scenario: 图片形状带有超链接

- **GIVEN** PPTX 幻灯片包含一张内嵌图片，且该图片形状设置了超链接指向 `https://example.com/report.pdf`
- **WHEN** 解析该图片形状
- **THEN** `structured_data.links` SHALL 包含条目，`url` 为超链接地址，`link_type` 为 `document`
- **AND** `ParsedElement.text` SHALL 包含超链接 URL 信息

#### Scenario: 使用公共 classify_link 函数分类资源

- **GIVEN** 任意 PPTX 超链接 URL
- **WHEN** 解析器判断该 URL 的资源类型
- **THEN** 系统 SHALL 使用 `parsers.utils.classify_link` 公共函数进行分类
- **AND** 返回类型为 `image`、`video`、`audio`、`document` 或 `url` 之一
- **AND** 不再使用解析器内部的重复分类逻辑

#### Scenario: 使用公共 guess_mime 推断 MIME 类型

- **GIVEN** PPTX 解析器需要推断资源 URL 的 MIME 类型
- **WHEN** 创建 Asset 时
- **THEN** 系统 SHALL 使用 `parsers.utils.guess_mime` 公共函数
- **AND** 不再使用解析器内部的 `_guess_mime` 方法

#### Scenario: 多超链接文本形状处理

- **GIVEN** PPTX 文本框中包含多个运行（run），部分运行设置了超链接，部分没有
- **WHEN** 解析该文本框
- **THEN** `structured_data.links` SHALL 仅包含有超链接的运行
- **AND** `ParsedElement.text` SHALL 保留所有文本内容（含超链接和非超链接文字）
