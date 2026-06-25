## MODIFIED Requirements

### Requirement: 解析过程中创建 Document 和 Asset 记录

系统 SHALL 在解析时为文档创建 Document 记录（含 `category`），为每个识别到的资源创建 Asset 记录。

#### Scenario: 创建 Document 记录

- **WHEN** 文档提交解析
- **THEN** 创建 Document 记录，包含 `doc_id`、`title`、`source_type`、`source_uri`、`source_hash`、`version=1`、`status="processing"`、`category` 和时间戳
- **AND** 若 `category` 未指定，默认值为 `"通用"`
- **AND** 若文档来自嵌入文档，记录 `parent_doc_id`、`root_doc_id` 和 `metadata.embed_path`
- **AND** 若文档为更新版本，记录 `previous_doc_id` 指向被替换的文档

#### Scenario: 为图片创建 Asset 记录

- **WHEN** 解析到图片链接
- **THEN** 创建 Asset 记录，包含 `asset_id`、`doc_id`、`source_element_id`、`asset_type="image"`、`original_uri`、`storage_uri=null`、`content_hash`、`status="ready"`、`extracted_text=null`、`error_message=null`
- **AND** Asset 的 `metadata` 不包含 `mime_type` 键（由后续处理器设置）

#### Scenario: 为视频链接创建 Asset 记录

- **WHEN** 解析到视频 URL 或视频链接
- **THEN** 创建 Asset 记录，包含 `asset_type="video"`、`original_uri`、`storage_uri=null`、`status="ready"` 和来源元素信息
- **AND** 不强制下载或理解视频内容
- **AND** Asset 的 `metadata` 不包含 `mime_type` 键

## ADDED Requirements

### Requirement: Element 先于 Asset 写入 PG

系统 SHALL 在 `_run_create` 中先将 ParsedElement 批量持久化到 PostgreSQL，再将 Asset 逐条处理并持久化。Element 为核心数据，优先保证持久化。

#### Scenario: Element 写入成功后再处理 Asset

- **WHEN** `_run_create` 执行
- **THEN** `create_batch(elements)` 在 `_prepare_assets(assets)` 之前调用
- **AND** Element 持久化失败时 Asset 处理不启动

#### Scenario: Asset 处理失败不影响已持久化的 Element

- **GIVEN** Element 已成功写入 PG
- **WHEN** 后续 `_prepare_assets` 中某个 Asset 处理失败（如 LLM 视觉调用超时）
- **THEN** 已持久化的 Element 不受影响
- **AND** 失败的 Asset 标记为 `status=failed`

### Requirement: image/video 类 Asset 并发处理

系统 SHALL 在 `_prepare_assets` 中对 image、video、image_link、video_link 类型的 Asset 使用线程池并发处理，document_link 保持串行处理。

#### Scenario: 多个图片并发处理

- **GIVEN** 文档包含 5 张内嵌图片
- **WHEN** `_prepare_assets` 处理
- **THEN** 5 张图片在最多 4 个线程中并发执行（魔数校验、视觉理解、MinIO 上传）
- **AND** 所有图片处理完成后继续后续流程

#### Scenario: document_link 串行处理

- **GIVEN** 文档包含 document_link 类型的 Asset
- **WHEN** `_prepare_assets` 处理
- **THEN** document_link 在主线程中串行执行
- **AND** 不被提交到线程池

#### Scenario: 并发处理中单个 Asset 失败不阻塞其他

- **GIVEN** 3 个图片并发处理，其中 1 个视觉调用失败
- **WHEN** `_prepare_assets` 执行
- **THEN** 失败的 Asset 标记为 `status=failed`
- **AND** 其余 2 个 Asset 正常完成处理
- **AND** 入库流程继续

### Requirement: ParsedElement 批量写入优化

系统 SHALL 在 `ParsedElementRepository.create_batch()` 中使用批量 INSERT 语句代替逐条 merge，提升大批量元素写入性能。

#### Scenario: 批量写入 100 个元素

- **GIVEN** 文档解析出 100 个 ParsedElement
- **WHEN** 调用 `create_batch(elements)`
- **THEN** 使用单条批量 INSERT 语句写入
- **AND** 所有元素在同一事务中提交
