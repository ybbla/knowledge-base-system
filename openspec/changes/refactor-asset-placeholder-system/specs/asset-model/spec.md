## MODIFIED Requirements

### Requirement: Asset 数据模型字段
Asset Pydantic 模型 SHALL 包含以下字段，语义如下：

| 字段 | 嵌入(image/video) | 链接(image_link/video_link/doc_link) | 网页(web_link) |
|------|-------------------|--------------------------------------|----------------|
| original_uri | "" | 原始 URL | 原始 URL |
| storage_uri | MinIO key | 下载后 MinIO key | None |
| display_text | "" | 链接锚文本 | 链接锚文本 |
| _data (运行时) | 字节数据 | 空 | 空 |

#### Scenario: 嵌入图片 Asset 创建
- **WHEN** 创建 asset_type=image 的 Asset
- **THEN** original_uri=""，display_text=""
- **AND** storage_uri 在 MinIO 上传后回填

#### Scenario: 链接 Asset 创建
- **WHEN** 创建 asset_type=image_link 的 Asset，链接文字 "photo.jpg"，URL "https://example.com/photo.jpg"
- **THEN** original_uri="https://example.com/photo.jpg"，display_text="photo.jpg"
- **AND** storage_uri 在下载上传后回填

#### Scenario: web_link Asset 创建
- **WHEN** 创建 asset_type=web_link 的 Asset
- **THEN** original_uri 存储 URL，storage_uri=None
- **AND** 不触发下载

### Requirement: AssetType 枚举包含 web_link
AssetType 枚举 SHALL 包含 `web_link = "web_link"` 值。

#### Scenario: 所有 6 种类型可用
- **WHEN** 查询 AssetType 枚举
- **THEN** SHALL 包含 image, video, image_link, video_link, document_link, web_link
