# Document Ingestion (Delta)

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

#### Scenario: 为视频链接创建 Asset 记录
- **WHEN** 解析到视频 URL 或视频链接
- **THEN** 创建 Asset 记录，包含 `asset_type="video"`、`original_uri`、`storage_uri=null`、`status="ready"` 和来源元素信息
- **AND** 不强制下载或理解视频内容

### Requirement: 状态流转简化

文档状态 SHALL 从 `processing` 开始，成功后变为 `active`，失败后变为 `failed`。不再使用 `pending` 状态。入库流程 SHALL NOT 维护独立的 JobStatus 生命周期，而是同步地将文档状态从 `processing` 更新为 `active` 或 `failed`。

#### Scenario: 文档初始状态
- **WHEN** 文档被创建
- **THEN** 初始状态为 `processing`

#### Scenario: 入库成功
- **WHEN** 文档完成解析、语义抽取和索引全部步骤
- **THEN** 状态变为 `active`

#### Scenario: 入库失败
- **WHEN** 文档入库过程中任一步骤抛出异常
- **THEN** 状态变为 `failed`
- **AND** `error_message` 记录失败原因

### Requirement: 解析后生成知识块并直接索引

系统 SHALL 在语义抽取生成 KnowledgeChunk 后，直接将知识块写入向量索引和 BM25 索引。不再通过 ChunkIndexStatus 追踪索引进度。索引失败 SHALL 导致文档状态变为 `failed`。

#### Scenario: 知识块索引成功
- **WHEN** KnowledgeChunk 成功写入 Milvus 和 BM25 索引
- **THEN** 知识块保持 `active` 状态，无需索引状态字段

#### Scenario: 知识块索引失败
- **WHEN** KnowledgeChunk 写入索引时发生异常
- **THEN** 所属 Document 的 `status` SHALL 变更为 `failed`
- **AND** `error_message` SHALL 记录索引失败的详细信息

### Requirement: 处理递归嵌入文档并设置边界

系统 SHALL 递归解析嵌入文档至可配置的最大深度，并支持去重。系统 MUST 在一次入库任务中只解析并提交一次根文档元素；递归加载只能补充嵌入文档产生的 Document 和 ParsedElement，不得重复返回根文档 ParsedElement。

#### Scenario: 根文档只解析一次
- **GIVEN** 文档 A 不包含嵌入文档
- **WHEN** 提交文档 A 入库
- **THEN** 语义抽取层只接收文档 A 首次解析产生的 ParsedElement
- **AND** 文档 A 的标题、段落、表格或资源元素不得因递归加载重复出现

#### Scenario: 根文档包含嵌入文档时不重复根元素
- **GIVEN** 文档 A 包含嵌入文档 B
- **WHEN** 提交文档 A 入库
- **THEN** 语义抽取层接收文档 A 的 ParsedElement 一次
- **AND** 系统继续递归解析文档 B 并追加文档 B 的 ParsedElement
- **AND** 文档 A 的 ParsedElement 不因发现文档 B 被再次解析或再次追加

#### Scenario: 深度限制内递归解析
- **GIVEN** 文档 A 嵌入文档 B，文档 B 嵌入文档 C，max_depth=3
- **WHEN** 提交文档 A 入库
- **THEN** 三个文档全部被解析，每个 Document 的 `parent_doc_id` 和 `root_doc_id` 正确指向文档 A

#### Scenario: 超出最大深度
- **GIVEN** 文档 A 在深度 3 处嵌入文档 B，max_depth=3
- **WHEN** 提交文档 A 入库
- **THEN** 文档 B 不被递归解析，其 Document 记录标记 `metadata.skipped_reason="max_depth_exceeded"`

#### Scenario: 重复文档跳过
- **GIVEN** 同一文档（相同 `source_hash`）在递归链路中遇到两次
- **WHEN** 提交根文档入库
- **THEN** 重复文档被跳过，标记 `metadata.skipped_reason="duplicated_document"`

#### Scenario: 外部资源阶段 1 仅识别关联
- **GIVEN** 文档包含图片、视频或附件链接
- **WHEN** 提交文档入库
- **THEN** 系统创建 Asset 并与 ParsedElement 关联
- **AND** 不要求下载到 MinIO、不要求生成 `storage_uri`，后续资源处理可异步补齐

## REMOVED Requirements

### Requirement: 入库请求仅接受 source_uri
**Reason**: `/ingest` 端点整体移除，入库统一通过 `POST /api/v1/documents/upload` 或 `POST /api/v1/documents` 触发。不再有独立的 `/ingest` 接口。
**Migration**: 使用 `POST /api/v1/documents/upload` 上传文件并自动触发入库。

### Requirement: ChunkStatus.superseded
**Reason**: 不再需要 superseded 状态，旧版本知识块直接用 deleted 状态。
**Migration**: 历史数据中的 superseded 状态转换为 deleted 状态。
