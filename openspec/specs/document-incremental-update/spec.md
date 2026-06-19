# Document Incremental Update

## Purpose

支持已入库文档的增量更新——通过显式指定 `doc_id` 触发更新流程，版本号递增，旧知识块标记 `superseded` 而非物理删除，嵌入子文档级联更新。

> 新建自 change `document-dedup-incremental-update`，日期 2026-06-15。

## Requirements

### Requirement: IngestDocument 模型包含 source_hash 字段

v1 文档上传和创建接口 SHALL 在 Document 记录上保存 `source_hash`。`POST /api/v1/documents/{doc_id}/ingest` SHALL 从已有 Document 读取 `source_hash` 执行更新检测，不再要求客户端提交旧 `/ingest` 的 `IngestDocument` 请求体。旧版 `POST /ingest` 在更新分支中，当 `existing.source_hash` 和 `item.source_hash` 均为空字符串时，系统 SHALL NOT 将其误判为 `no_change` 跳过入库。

#### Scenario: 创建文档时保存 source_hash
- **GIVEN** 客户端通过 v1 上传或 URI 创建文档
- **WHEN** 请求包含或系统计算出 `source_hash`
- **THEN** 系统 SHALL 将 `source_hash` 保存到 Document 记录

#### Scenario: 已有文档入库时读取 source_hash
- **GIVEN** 文档 `doc_xxx` 已保存 `source_hash`
- **WHEN** 客户端请求 `POST /api/v1/documents/doc_xxx/ingest`
- **THEN** 系统 SHALL 从 Document 记录读取 `source_hash`
- **AND** 系统 SHALL 使用该值执行增量更新检测

#### Scenario: 已有文档缺少 source_hash
- **GIVEN** 文档 `doc_legacy` 缺少 `source_hash`（为空字符串或 None）
- **WHEN** 客户端请求 `POST /api/v1/documents/doc_legacy/ingest`
- **THEN** 系统 SHALL 允许按 `source_uri` 执行入库
- **AND** 系统 SHALL 在响应或任务错误中给出可诊断信息，避免静默失败

#### Scenario: 双方 source_hash 均为空时不应跳过入库
- **GIVEN** 已有文档的 `source_hash` 为空字符串，请求中的 `source_hash` 也为空字符串
- **WHEN** 通过旧版 `POST /ingest` 提交增量更新请求
- **THEN** 系统 SHALL NOT 判定为 `no_change` 跳过入库
- **AND** 系统 SHALL 正常进入入库流程（因为空 hash 表示 hash 未计算，不能证明内容未变化）

### Requirement: 入库请求支持可选 doc_id 触发更新

系统 SHALL 通过路径参数 `doc_id` 在 `POST /api/v1/documents/{doc_id}/ingest` 中指定已有文档，并根据 `mode=incremental` 或 `mode=force` 执行增量更新或强制重建；新建文档入库 SHALL 通过 `POST /api/v1/documents` 或 `POST /api/v1/documents/upload` 的 `ingest_after_create=true` 触发。

#### Scenario: 路径 doc_id 触发增量更新
- **GIVEN** `doc_id` 指向一个存在的文档，且其来源内容相比当前索引版本发生变化
- **WHEN** 客户端请求 `POST /api/v1/documents/{doc_id}/ingest?mode=incremental`
- **THEN** 系统 SHALL 进入增量更新流程
- **AND** 系统 SHALL 递增版本、标记旧知识块为 `superseded`、重新解析并索引

#### Scenario: 路径 doc_id 内容未变化
- **GIVEN** `doc_id` 指向一个存在的文档，且来源内容未变化
- **WHEN** 客户端请求 `POST /api/v1/documents/{doc_id}/ingest?mode=incremental`
- **THEN** 系统 SHALL 跳过不必要的解析和索引
- **AND** 任务详情 SHALL 提供 `no_change` 或等价可展示结果

#### Scenario: 路径 doc_id 不存在
- **GIVEN** `doc_id` 在数据库中不存在
- **WHEN** 客户端请求 `POST /api/v1/documents/{doc_id}/ingest`
- **THEN** 系统 SHALL 返回 404
- **AND** 错误 `code` SHALL 为 `DOCUMENT_NOT_FOUND`

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

旧 `/ingest` 的 `warnings` 语义 SHALL 迁移到 v1 响应结构：v1 上传、创建和入库接口 SHALL 通过 `data` 或 `meta.warnings` 返回重复内容、未变化跳过、兼容降级等可展示提示。旧 `/ingest` 在兼容期内 SHALL 保持原有 `warnings` 字段。

#### Scenario: 重复文档被跳过
- **GIVEN** 客户端提交与已有活跃文档相同 hash 的新文档创建请求
- **WHEN** 系统检测到重复内容
- **THEN** v1 响应 SHALL 包含 `DOCUMENT_DUPLICATE` 错误或 `duplicate=true` 数据
- **AND** 响应 SHALL 包含 `existing_doc_id`

#### Scenario: 内容未变化的已有文档入库
- **GIVEN** 客户端对已有文档触发增量入库，且来源内容未变化
- **WHEN** 系统完成更新检测
- **THEN** 任务详情或响应元信息 SHALL 表明该任务因 `no_change` 跳过解析和索引
