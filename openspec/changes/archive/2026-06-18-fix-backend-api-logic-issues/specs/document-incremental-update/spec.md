## MODIFIED Requirements

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
