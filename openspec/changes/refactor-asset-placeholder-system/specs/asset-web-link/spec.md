## ADDED Requirements

### Requirement: AssetType 包含 web_link 类型
AssetType 枚举 SHALL 包含 `web_link` 类型，用于表示普通网页链接。

#### Scenario: 链接文字无识别后缀时归类为 web_link
- **WHEN** 解析器遇到超链接文字为 "百度"（无 .png/.mp4/.pdf 等后缀）
- **THEN** 系统 SHALL 创建 asset_type=web_link 的 Asset
- **AND** original_uri 存储原始 URL
- **AND** storage_uri 为空
- **AND** display_text 存储 "百度"

### Requirement: web_link 资源不触发下载
web_link 类型的 Asset SHALL NOT 触发任何下载或 MinIO 上传操作。

#### Scenario: pipeline 处理 web_link
- **WHEN** ingestion pipeline 的 _prepare_assets 遇到 asset_type=web_link
- **THEN** 系统 SHALL 仅调用 asset_store.put() 持久化 Asset
- **AND** 不调用任何下载函数
