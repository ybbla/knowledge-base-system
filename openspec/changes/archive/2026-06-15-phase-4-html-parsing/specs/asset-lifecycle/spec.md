## MODIFIED Requirements

### Requirement: 视频链接资源化

系统 SHALL 在解析阶段识别视频链接（HTML `<video>`、HTML `<source>`、视频 iframe、Markdown `![video](...)`、YouTube/Vimeo/常见视频文件 URL 等），创建 `Asset(asset_type=video, status=pending)` 记录，阶段 3 和阶段 4 不做下载和语义提取。

#### Scenario: 识别视频链接并创建 Asset

- **WHEN** 解析器在文档中识别到视频 URL
- **THEN** 系统创建 Asset 记录（`asset_type=video`，`status=pending`，`original_uri`=视频 URL，`storage_uri=null`，`extracted_text=null`）

#### Scenario: 识别 HTML 视频标签

- **GIVEN** HTML 文档包含 `video`、`source` 或指向视频平台的 `iframe`
- **WHEN** HTML 解析器处理该文档
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** Asset metadata 记录来源标签和属性

#### Scenario: 视频 Asset 关联到知识块

- **WHEN** 视频附近有相关的知识块
- **THEN** 知识块的 `asset_refs` 中关联该视频 Asset（`relation=demonstration` 或 `illustration`），即使 `storage_uri` 为空

#### Scenario: 不支持下载的视频保留外部链接

- **WHEN** 视频 URL 指向外部平台不可下载
- **THEN** Asset 的 `original_uri` 保留原始链接，`storage_uri` 为 null，不影响入库流程

## ADDED Requirements

### Requirement: HTML 附件类资源识别

系统 SHALL 在 HTML 解析阶段识别 `iframe`、`embed`、`object` 和常见下载链接中的附件类资源候选，创建或保留可追溯来源信息，且不得在解析阶段下载或递归解析这些资源。

#### Scenario: 识别 iframe 附件

- **GIVEN** HTML 文档包含非视频 `iframe src="https://example.com/embed/report"`
- **WHEN** HTML 解析器处理该文档
- **THEN** 系统 SHALL 保留该 iframe URL 的来源信息
- **AND** 若创建 Asset，则 Asset 的 `asset_type` 为 `attachment`
- **AND** Asset 的 `status` 为 `pending`

#### Scenario: 识别 object 或 embed 附件

- **GIVEN** HTML 文档包含 `object data="https://example.com/manual.pdf"` 或 `embed src="https://example.com/manual.pdf"`
- **WHEN** HTML 解析器处理该文档
- **THEN** 系统创建或保留附件类资源引用
- **AND** 阶段 4 不下载该附件
- **AND** 阶段 4 不递归解析该附件内容

#### Scenario: 附件数量受资源限制保护

- **GIVEN** HTML 文档包含大量附件链接
- **WHEN** 入库管线处理解析器返回的 Asset
- **THEN** 系统 SHALL 继续使用 `MAX_ASSETS_PER_DOC` 限制单文档资源数量
- **AND** 超出部分按照现有资源生命周期规则标记为 `skipped`
