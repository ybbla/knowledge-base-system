## Why

当前 Asset 数据模型存在三方面问题：1) 嵌入资源与外部链接资源字段语义混乱（嵌入图片的 `original_uri` 使用 `docx://` 伪协议，与真实 HTTP 链接混在同一字段）；2) 链接资源分类依赖 URL 而非用户可见的链接文字，导致 `天空.png` 超链接到 `https://xxx.com/abc` 时无法正确识别为图片链接；3) 占位符格式 `[图片: xxx][image1]` 冗余且不统一（md/dox/pdf 各解析器风格不同）。普通网页链接散落在 `metadata["link_urls"]` 中，缺乏统一管理。

## What Changes

- **BREAKING**: `AssetType` 新增 `web_link` 枚举值，链接兜底类型从 `None` 改为 `web_link`
- **BREAKING**: `Asset` 新增 `display_text` 字段存储链接文字（嵌入类型为空，链接类型为锚文本）
- **BREAKING**: 嵌入类型（image/video）的 `original_uri` 改为空字符串，`storage_uri` 存储 MinIO key
- **BREAKING**: 占位符统一为 `{{image:1}}` `{{video:2}}` `{{doc:3}}` `{{web:4}}` 格式
- **BREAKING**: 链接文字在段落文本中被占位符替换，不再保留原文
- 新增 `classify_link_text()` 工具函数，通过链接文字后缀分类：`.png/.jpg` → `image_link`，`.mp4/.mov` → `video_link`，`.pdf/.docx` → `document_link`，其余 → `web_link`
- 各解析器统一适配新的 Asset 字段语义和占位符格式
- `_data` 保持运行时私有属性不入库，嵌入资源字节数据仅用于 MinIO 上传

## Capabilities

### New Capabilities
- `asset-web-link`: 普通网页链接作为 web_link 类型统一管理，不再散落在 metadata 中
- `asset-display-text`: Asset 新增 display_text 字段，统一存储链接锚文本
- `classify-link-by-text`: 新增 classify_link_text() 工具函数，按链接文字后缀分类资源类型
- `unified-placeholder`: 统一占位符格式 {{type:n}}，所有解析器行为一致

### Modified Capabilities
- `asset-model`: Asset 数据模型字段语义变更（original_uri/storage_uri/display_text）
- `docx-parser`: 适配新 Asset 字段和占位符格式，链接分类改为按文字后缀
- `markdown-parser`: 同上
- `pdf-parser`: 同上
- `html-parser`: 同上
- `pptx-parser`: 同上
- `xlsx-parser`: 同上
- `asset-processing`: 资源处理器适配新 original_uri 语义

## Impact

- **数据模型**: `app/core/models.py` — AssetType 枚举、Asset 字段
- **解析器**: `parsers/docx_parser.py`, `parsers/markdown_parser.py`, `parsers/pdf_parser.py`, `parsers/html_parser.py`, `parsers/pptx_parser.py`, `parsers/xlsx_parser.py`
- **工具函数**: `parsers/utils.py` — 新增 `classify_link_text()`
- **资源处理**: `assets/asset_processor.py`, `assets/minio_store.py`
- **入库流程**: `ingestion/pipeline.py`
- **语义抽取**: `llm/semantic_extractor.py`
- **API 层**: `app/api/v1/documents.py` — 统计接口无影响
- **测试**: 所有引用旧占位符格式和旧 Asset 字段的测试文件
- **数据库**: PG assets 表自动适配新字段，旧数据 `original_uri` 为伪协议的记录需评估迁移
