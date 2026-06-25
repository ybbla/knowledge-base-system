## MODIFIED Requirements

### Requirement: 资源处理器适配新 original_uri 语义
asset_processor.py 和 minio_store.py SHALL 适配嵌入类型 original_uri 为空的新语义。

#### Scenario: process_image 不再从 original_uri 降级读数据
- **WHEN** process_image 处理 asset_type=image 的 Asset
- **THEN** 系统 SHALL 仅从 `_data` 读取字节数据
- **AND** 不再调用 `read_uri_bytes(asset.original_uri)` 降级

#### Scenario: process_video 不再从 original_uri 降级读数据
- **WHEN** process_video 处理 asset_type=video 的 Asset
- **THEN** 系统 SHALL 仅从 `_data` 读取字节数据
- **AND** 不再从 original_uri 降级

#### Scenario: 文件名从 metadata 获取
- **WHEN** `_process_image_data` 或 `_process_video_data` 需要文件名
- **THEN** 系统 SHALL 从 `asset.metadata.get("filename")` 获取
- **AND** 降级从 `asset.display_text` 获取（链接类型）

#### Scenario: pipeline 处理 web_link
- **WHEN** `_prepare_assets` 遇到 asset_type=web_link
- **THEN** 系统 SHALL 仅调用 `asset_store.put(asset)` 持久化
- **AND** 不调用任何下载或处理器函数

### Requirement: semantic_extractor 适配新字段
semantic_extractor SHALL 根据 asset_type 选择正确的 URL 来源。

#### Scenario: 嵌入资源取 storage_uri
- **WHEN** `_elements_to_json` 注入 Asset URL 且 asset_type 为 image 或 video
- **THEN** 系统 SHALL 使用 `asset.storage_uri` 作为 URL

#### Scenario: 链接资源取 original_uri
- **WHEN** `_elements_to_json` 注入 Asset URL 且 asset_type 为链接类型
- **THEN** 系统 SHALL 使用 `asset.original_uri` 作为 URL
