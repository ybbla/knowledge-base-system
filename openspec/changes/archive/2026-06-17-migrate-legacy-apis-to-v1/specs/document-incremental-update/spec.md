## MODIFIED Requirements

### Requirement: IngestDocument 模型包含 source_hash 字段
v1 文档上传和创建接口 SHALL 在 Document 记录上保存 `source_hash`。`POST /api/v1/documents/{doc_id}/ingest` SHALL 从已有 Document 读取 `source_hash` 执行更新检测，不再要求客户端提交旧 `/ingest` 的 `IngestDocument` 请求体。

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
- **GIVEN** 文档 `doc_legacy` 缺少 `source_hash`
- **WHEN** 客户端请求 `POST /api/v1/documents/doc_legacy/ingest`
- **THEN** 系统 SHALL 允许按 `source_uri` 执行入库
- **AND** 系统 SHALL 在响应或任务错误中给出可诊断信息，避免静默失败

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
