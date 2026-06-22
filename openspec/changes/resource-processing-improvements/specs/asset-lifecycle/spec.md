# Asset Lifecycle Delta

## REMOVED Requirements

### Requirement: 入库资源数量限制

**Reason**: 资源数量和大小限制已从配置中移除，不再需要对单个文档的资源数或单资源大小进行硬性限制。
**Migration**: 无需迁移。之前受限制的资源现在会正常处理。

### Requirement: 附件类资源识别

**Reason**: `AssetType.attachment` 枚举值已移除，替换为 `document_link`。子文档通过 `process_document_link` 走完整入库流水线，不再依赖 `RecursiveLoader`。
**Migration**: 所有创建 `attachment` 类型 Asset 的代码改为创建 `document_link` 类型。`RecursiveLoader` 一并移除。

### Requirement: 嵌入子文档递归加载

**Reason**: `RecursiveLoader` 创建的子 Document `source_uri=""` 导致解析器无法获取内容，实际不可用。被 `document_link` 的完整入库流程替代。
**Migration**: Markdown `[[link]]` 改为创建 `document_link` Asset，走 HTTP下载→MinIO上传→子文档ingest 流程。

## MODIFIED Requirements

### Requirement: 视频链接资源化

系统 SHALL 在解析阶段识别视频链接，创建 `Asset(asset_type=video_link)` 记录。入库时对视频链接执行 HTTP 下载、视觉理解和 MinIO 上传。

#### Scenario: 识别视频链接并创建 Asset
- **WHEN** 解析器在文档中识别到视频 URL
- **THEN** 系统创建 Asset 记录（`asset_type=video_link`，`status=ready`，`original_uri`=视频 URL）

#### Scenario: 视频链接下载并上传 MinIO
- **WHEN** 视频 Asset 进入 `_prepare_assets` 处理
- **THEN** 系统执行 HTTP 下载获取视频字节
- **AND** 调用视觉理解模型生成内容描述
- **AND** 上传视频到 MinIO，更新 `storage_uri`

#### Scenario: 识别 HTML 视频标签
- **GIVEN** HTML 文档包含 `video`、`source` 或指向视频平台的 `iframe`
- **WHEN** HTML 解析器处理该文档
- **THEN** 系统创建 `asset_type="video_link"` 的 Asset
- **AND** Asset metadata 记录来源标签和属性

#### Scenario: 视频 Asset 关联到知识块
- **WHEN** 视频附近有相关的知识块
- **THEN** 知识块的 `asset_refs` 中关联该视频 Asset（`relation=demonstration` 或 `illustration`）

#### Scenario: 不支持下载的视频保留外部链接
- **WHEN** 视频 URL 指向外部平台不可下载
- **THEN** Asset 的 `original_uri` 保留原始链接，`storage_uri` 为 null，不影响入库流程

### Requirement: 图片下载与校验

系统 SHALL 在入库时根据 Asset 类型执行不同起点的图片处理：内嵌图片直接从 `_data` 读取，外部图片链接先 HTTP 下载。

#### Scenario: 内嵌图片直接读取
- **WHEN** Asset 类型为 `image`（解析器提供了内嵌字节）
- **THEN** 系统从 `asset._data` 读取字节，进入魔数校验→去重→视觉理解→MinIO 上传管线

#### Scenario: 外部图片链接先下载
- **WHEN** Asset 类型为 `image_link`（仅有 URL）
- **THEN** 系统先执行 HTTP 下载获取字节，下载成功后进入与内嵌图片相同的处理管线

#### Scenario: 图片类型校验
- **WHEN** 获取到图片字节后
- **THEN** 系统校验文件魔数为常见图片格式（PNG/JPEG/GIF/WebP/BMP），非图片则标记 `status=failed`

#### Scenario: 下载失败不阻塞入库
- **WHEN** 图片下载超时、网络不可达或返回非 200
- **THEN** 系统创建 Asset（`status=failed`，`error_message` 记录失败原因），不阻塞文档其他元素的处理
