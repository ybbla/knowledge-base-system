## MODIFIED Requirements

### Requirement: 图片下载与校验

系统 SHALL 在入库时对解析出的图片资源执行下载、类型校验和大小限制检查。

#### Scenario: 下载远程图片

- **WHEN** 解析器提取到的图片 `original_uri` 为 HTTP/HTTPS URL
- **THEN** 系统下载图片字节，超时时间 10 秒，最大大小 100MB（`MAX_ASSET_SIZE_MB`），超过则跳过并记录 WARNING

#### Scenario: 本地/内嵌图片直接读取

- **WHEN** 解析器提取到的图片来自本地文件、DOCX 内嵌图片或 PPTX 内嵌图片
- **THEN** 系统直接读取文件字节或解析器提供的内嵌字节，校验大小和类型

#### Scenario: 图片类型校验

- **WHEN** 获取到图片字节后
- **THEN** 系统校验文件魔数为常见图片格式（PNG/JPEG/GIF/WebP/BMP），非图片则标记 `status=failed`

#### Scenario: 下载失败不阻塞入库

- **WHEN** 图片下载超时、网络不可达或返回非 200
- **THEN** 系统创建 Asset（`status=failed`，`error_message` 记录失败原因），不阻塞文档其他元素的处理

### Requirement: 视频链接资源化

系统 SHALL 在解析阶段识别视频链接（HTML `<video>`、HTML `<source>`、视频 iframe、Markdown `![video](...)`、XLSX 单元格视频 URL、PPTX 文本或超链接视频 URL、YouTube/Vimeo/常见视频文件 URL 等），创建 `Asset(asset_type=video, status=pending)` 记录，阶段 3 和阶段 4 不做下载和语义提取。

#### Scenario: 识别视频链接并创建 Asset

- **WHEN** 解析器在文档中识别到视频 URL
- **THEN** 系统创建 Asset 记录（`asset_type=video`，`status=pending`，`original_uri`=视频 URL，`storage_uri=null`，`extracted_text=null`）

#### Scenario: 识别 HTML 视频标签

- **GIVEN** HTML 文档包含 `video`、`source` 或指向视频平台的 `iframe`
- **WHEN** HTML 解析器处理该文档
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** Asset metadata 记录来源标签和属性

#### Scenario: 识别 PPTX 视频链接

- **GIVEN** PPTX 文档的文本框或形状超链接包含视频 URL
- **WHEN** PPTX 解析器处理该文档
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** Asset metadata 记录 `slide_index`、`slide_number` 和形状来源信息
- **AND** 阶段 4 不下载或理解视频内容

#### Scenario: 视频 Asset 关联到知识块

- **WHEN** 视频附近有相关的知识块
- **THEN** 知识块的 `asset_refs` 中关联该视频 Asset（`relation=demonstration` 或 `illustration`），即使 `storage_uri` 为空

#### Scenario: 不支持下载的视频保留外部链接

- **WHEN** 视频 URL 指向外部平台不可下载
- **THEN** Asset 的 `original_uri` 保留原始链接，`storage_uri` 为 null，不影响入库流程

### Requirement: 附件类资源识别

系统 SHALL 在 HTML 和 PPTX 解析阶段识别 iframe、embed、object、形状超链接和常见下载链接中的附件类资源候选，创建或保留可追溯来源信息，且不得在解析阶段下载或递归解析这些资源。

#### Scenario: 识别 HTML iframe 附件

- **GIVEN** HTML 文档包含非视频 `iframe src="https://example.com/embed/report"`
- **WHEN** HTML 解析器处理该文档
- **THEN** 系统 SHALL 保留该 iframe URL 的来源信息
- **AND** 若创建 Asset，则 Asset 的 `asset_type` 为 `attachment`
- **AND** Asset 的 `status` 为 `pending`

#### Scenario: 识别 HTML object 或 embed 附件

- **GIVEN** HTML 文档包含 `object data="https://example.com/manual.pdf"` 或 `embed src="https://example.com/manual.pdf"`
- **WHEN** HTML 解析器处理该文档
- **THEN** 系统创建或保留附件类资源引用
- **AND** 阶段 4 不下载该附件
- **AND** 阶段 4 不递归解析该附件内容

#### Scenario: 识别 PPTX 附件或外部文件链接

- **GIVEN** PPTX 文档的形状超链接指向 PDF、DOCX、XLSX、PPTX、ZIP 或其他下载文件
- **WHEN** PPTX 解析器处理该文档
- **THEN** 系统创建或保留附件类资源引用
- **AND** 若创建 Asset，则 Asset 的 `asset_type` 为 `attachment`
- **AND** Asset metadata 记录 `slide_index`、`slide_number`、形状来源和原始链接
- **AND** 阶段 4 不下载或递归解析该附件内容

#### Scenario: 附件数量受资源限制保护

- **GIVEN** HTML 或 PPTX 文档包含大量附件链接
- **WHEN** 入库管线处理解析器返回的 Asset
- **THEN** 系统 SHALL 继续使用 `MAX_ASSETS_PER_DOC` 限制单文档资源数量
- **AND** 超出部分按照现有资源生命周期规则标记为 `skipped`
