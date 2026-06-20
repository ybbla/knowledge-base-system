# Asset Lifecycle

## Purpose

管理入库过程中图片、视频等资源的完整生命周期：下载、校验、hash 去重、上传对象存储、创建 Asset 记录，并关联到知识块。视频链接在阶段 3 仅资源化，不做下载和语义提取。Asset 状态模型简化为 `ready`/`failed` 两态。

> 新建自 change `phase-3-milvus-minio`，日期 2026-06-12；更新自 change `simplify-status-model`，日期 2026-06-19。

## Requirements

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

### Requirement: Asset content_hash 去重

系统 SHALL 对每个 Asset 计算 `content_hash`（sha256），入库前检查是否已存在相同 hash 的 Asset，若存在则复用而非重复存储。

#### Scenario: 相同图片去重复用
- **WHEN** 图片的 sha256 hash 与已有 `status=ready` 的 Asset 匹配
- **THEN** 系统复用已有 Asset 的 `storage_uri`、`extracted_text` 等字段，仅新增当前 Asset 引用，不上传重复文件到 MinIO

#### Scenario: 不同图片创建新 Asset
- **WHEN** 图片的 sha256 hash 匹配不到已有 Asset
- **THEN** 系统创建新 Asset 记录，上传图片到 MinIO `kb-assets/{doc_id[:2]}/{doc_id}/{asset_id}/{file_name}`

#### Scenario: 去重仅检查 ready 状态的 Asset
- **WHEN** 存在 hash 相同但 `status=failed` 的 Asset
- **THEN** 系统重新尝试处理（下载、校验、上传），不跳过该资源

### Requirement: 图片上传 MinIO 并更新 Asset 状态

系统 SHALL 将图片上传到 MinIO `kb-assets` Bucket，更新 Asset 的 `storage_uri` 和 `status`。

#### Scenario: 图片上传成功
- **WHEN** 图片校验通过且未命中去重
- **THEN** 图片字节上传到 MinIO，Asset 状态更新为 `status=ready`，`storage_uri` 更新为 `minio://kb-assets/{doc_id[:2]}/{doc_id}/{asset_id}/{file_name}`

#### Scenario: 图片上传失败
- **WHEN** MinIO 上传出错（网络、权限、空间不足等）
- **THEN** Asset 状态更新为 `status=failed`，`error_message` 记录详细错误，继续处理后续资源

### Requirement: 视频链接资源化

系统 SHALL 在解析阶段识别视频链接，创建 `Asset(asset_type=video, status=ready)` 记录，不做下载和语义提取。

#### Scenario: 识别视频链接并创建 Asset
- **WHEN** 解析器在文档中识别到视频 URL
- **THEN** 系统创建 Asset 记录（`asset_type=video`，`status=ready`，`original_uri`=视频 URL，`storage_uri=null`，`extracted_text=null`）

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

#### Scenario: 视频 Asset 关联到知识块
- **WHEN** 视频附近有相关的知识块
- **THEN** 知识块的 `asset_refs` 中关联该视频 Asset（`relation=demonstration` 或 `illustration`），即使 `storage_uri` 为空

#### Scenario: 不支持下载的视频保留外部链接
- **WHEN** 视频 URL 指向外部平台不可下载
- **THEN** Asset 的 `original_uri` 保留原始链接，`storage_uri` 为 null，不影响入库流程

### Requirement: 入库资源数量限制

系统 SHALL 限制单文档处理的资源数量和单资源大小，防止资源爆炸。

#### Scenario: 单文档资源数超限
- **WHEN** 一个文档解析出的资源数超过 `MAX_ASSETS_PER_DOC`（默认 100）
- **THEN** 超出部分的资源不创建 Asset 记录，记录 WARNING 日志

#### Scenario: 单资源大小超限
- **WHEN** 图片或视频大小超过 `MAX_ASSET_SIZE_MB`（默认 100MB）
- **THEN** 该资源标记为 `status=failed`，`error_message` 记录 `max_asset_size_exceeded`

### Requirement: 附件类资源识别

系统 SHALL 在 HTML 和 PPTX 解析阶段识别附件类资源候选，创建或保留可追溯来源信息，且不得在解析阶段下载或递归解析这些资源。

#### Scenario: 识别 HTML iframe 附件
- **GIVEN** HTML 文档包含非视频 `iframe src="https://example.com/embed/report"`
- **WHEN** HTML 解析器处理该文档
- **THEN** 系统 SHALL 保留该 iframe URL 的来源信息
- **AND** 若创建 Asset，则 Asset 的 `asset_type` 为 `attachment`
- **AND** Asset 的 `status` 为 `ready`

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
- **AND** 超出部分不创建 Asset 记录，记录 WARNING 日志
