## Why

当前资源类型枚举（`image` / `video` / `audio` / `attachment`）与实际业务不匹配：`audio` 仅 PPTX 解析器偶尔产出且无处理逻辑，`attachment` 语义模糊（外链/嵌入文档引用/未知 URL 混在一起）。除 `image` 外的所有资源类型都没有下载→上传 MinIO 的生命周期管理。`RecursiveLoader` 创建的子 Document `source_uri=""` 导致 parser 拿到空内容，子文档递归解析实际不可用。

## What Changes

- **BREAKING**: 重构 `AssetType` 枚举：删除 `audio` 和 `attachment`，新增 `image_link`、`video_link`、`document_link`，保留 `image`
- 所有链接类型统一"HTTP下载 → MinIO上传"流程
- `image` 与 `image_link` 区别在起点（字节 vs URL），收敛后走同一条校验→去重→理解→上传管线
- `document_link` 下载后触发完整子文档入库流水线（创建子 Document → ingest），对标用户上传
- **BREAKING**: 移除 `RecursiveLoader`（含 `RecursiveLoadResult`），Markdown `[[link]]` 改为产出 `document_link` Asset
- 删除 `ElementType.embedded_document` 和 `ParsedElement.embedded_doc_id` 死字段
- 所有解析器适配新枚举
- **已完成**: 删除 `max_asset_size_mb` 和 `max_assets_per_doc` 配置项及关联逻辑；删除 `ParseResult.embedded_docs`；删除 `SourceLocation.char_start/char_end`

## Capabilities

### New Capabilities
- `asset-link-download`: 外部链接资源下载与 MinIO 上传，统一的 HTTP 下载→校验→上传流程
- `asset-type-refactor`: 重构 AssetType 枚举，拆分为语义明确的四种类型

### Modified Capabilities
- `asset-lifecycle`: Asset 元数据模型变更（枚举值改变），资源处理分支逻辑更新；移除 RecursiveLoader
- `image-vision-understanding`: image_link 加入图片视觉理解管线
- `video-vision-understanding`: video_link 加入视频视觉理解管线，补充 MinIO 上传

### Removed
- `RecursiveLoader` 及 `RecursiveLoadResult`：被 `document_link` 完整入库流程替代

## Impact

| 影响范围 | 说明 |
|---------|------|
| `app/core/models.py` | `AssetType` 枚举重构 |
| `assets/image_processor.py` | 新增 `process_image_link`、`process_document_link`，重构 `process_video` |
| `assets/downloader.py` | 新建，HTTP 下载工具函数 |
| `ingestion/pipeline.py` | `_prepare_assets` 分支适配 + 移除 RecursiveLoader 调用 |
| `ingestion/recursive_loader.py` | **删除** |
| `parsers/markdown_parser.py` | `[[link]]` 从 `embedded_doc_id` 改为 `document_link` Asset |
| `parsers/` (其余6个解析器) | 适配新枚举 |
| `tests/` | 更新所有相关测试，删除 `test_recursive_loader.py` |
