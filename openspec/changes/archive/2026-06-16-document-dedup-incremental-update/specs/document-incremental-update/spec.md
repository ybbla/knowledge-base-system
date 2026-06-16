## ADDED Requirements

### Requirement: IngestDocument 模型包含 source_hash 字段

`/ingest` 的 `IngestDocument` 模型 SHALL 新增必填字段 `source_hash`（字符串类型），由客户端从 `/upload` 响应中原样传入。系统依赖此字段执行去重检查和更新检测，不再从 MinIO 重新下载计算。

#### Scenario: 正常传入 source_hash
- **WHEN** 客户端调用 `/ingest` 且 `IngestDocument.source_hash` 有值
- **THEN** 系统直接使用该值执行去重或更新检测

#### Scenario: 缺少 source_hash
- **WHEN** 客户端调用 `/ingest` 且 `IngestDocument.source_hash` 为空
- **THEN** 系统返回 `422 Validation Error`

### Requirement: 入库请求支持可选 doc_id 触发更新

`/ingest` 的 `IngestDocument` 模型 SHALL 新增可选字段 `doc_id`。当 `doc_id` 有值时系统执行增量更新流程；无值时执行新建流程。

#### Scenario: 传入 doc_id 触发更新
- **WHEN** `/ingest` 请求中 `doc_id` 指向一个存在的文档，且请求中的 `source_hash` 与该文档当前 `source_hash` 不同
- **THEN** 系统进入增量更新流程：version 递增、旧知识块标记 `superseded`、重新解析和索引

#### Scenario: 传入 doc_id 但 source_hash 未变
- **WHEN** `/ingest` 请求中 `doc_id` 指向一个存在的文档，且请求中的 `source_hash` 与该文档当前 `source_hash` 相同
- **THEN** 系统跳过解析和索引，直接返回 `"no_change": true`

#### Scenario: 传入不存在的 doc_id
- **WHEN** `/ingest` 请求中 `doc_id` 在数据库中不存在
- **THEN** 系统返回 `404 Not Found` 错误，附带 `DocumentNotFoundError`

### Requirement: 文档版本递增

更新已有文档时，系统 SHALL 将 `version` 字段在原值基础上递增 1。新生成的 `ParsedElement`、`KnowledgeChunk` 的 `doc_version` SHALL 使用新的版本号。

#### Scenario: 首次更新文档
- **WHEN** 文档当前 `version = 1` 且触发更新
- **THEN** 文档 `version` 更新为 `2`，新生成的 element 和 chunk 的 `doc_version` 均为 `2`

#### Scenario: 多次更新文档
- **WHEN** 文档当前 `version = 3` 且触发更新
- **THEN** 文档 `version` 更新为 `4`

### Requirement: 旧知识块标记为 superseded

更新时，系统 SHALL 将旧版本的 `KnowledgeChunk` 在 PostgreSQL 和 Milvus 中同时标记为 `superseded`，而非物理删除。

#### Scenario: 旧知识块状态更新
- **WHEN** 文档更新流程中新 chunks 已成功写入索引
- **THEN** 系统将 `doc_id` 匹配且 `status='active'` 的旧 chunks 在 PostgreSQL 中 `status` 更新为 `superseded`，并在 Milvus 中 upsert 对应实体的 `status` 为 `superseded`

#### Scenario: 更新过程中旧版本 chunks 仍在索引中
- **WHEN** 新 chunks 正在解析和索引但旧 chunks 尚未标记 `superseded`
- **THEN** 检索可能同时返回新旧两个版本的 chunks（窗口期可接受）

### Requirement: 嵌入子文档级联更新

父文档更新时，系统 SHALL 级联处理所有 `root_doc_id` 等于该父文档 `doc_id` 的子文档，将它们一并重新解析和索引。

#### Scenario: 父文档有嵌入子文档时更新
- **WHEN** 文档 `doc_A`（有 `root_doc_id = doc_A` 的子文档 `doc_B`、`doc_C`）触发更新
- **THEN** `doc_A`、`doc_B`、`doc_C` 三者均重新解析，所有旧版本 chunks 均标记 `superseded`

#### Scenario: 父文档无嵌入子文档时更新
- **WHEN** 文档 `doc_A`（无 `root_doc_id = doc_A` 的子文档）触发更新
- **THEN** 仅 `doc_A` 被重新解析，无级联操作

### Requirement: /ingest 响应新增 warnings

`/ingest` 响应 SHALL 在 `warnings` 字段中返回被跳过的文档信息，包括跳过原因和已有文档 ID。

#### Scenario: 重复文档被跳过
- **WHEN** 入库请求中包含与已有活跃文档相同 hash 的新文档
- **THEN** 响应 `warnings` 中包含 `{"doc_id": "新文档ID", "reason": "duplicate_content", "existing_doc_id": "已有文档ID"}`
