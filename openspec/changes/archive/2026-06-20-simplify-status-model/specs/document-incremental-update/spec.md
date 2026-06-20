# Document Incremental Update (Delta)

## REMOVED Requirements

### Requirement: IngestDocument 模型包含 source_hash 字段
**Reason**: 增量更新逻辑整体移除。更新统一为"软删除旧文档 + 创建新文档"的全量替换模式，不再需要基于 `source_hash` 对比的 `no_change` 判定和增量 diff。
**Migration**: `source_hash` 字段在 Document 模型上保留，用于上传时的重复文件检测，但不用于增量更新判定。

### Requirement: 入库请求支持可选 doc_id 触发更新
**Reason**: `POST /api/v1/documents/{doc_id}/ingest` 端点整体移除。
**Migration**: 文档更新通过重新上传文件并指定 `replace_doc_id` + `confirm_replace=true` 实现。

### Requirement: 文档版本递增
**Reason**: 版本递增逻辑保留但简化——仅在"更新"操作（创建新文档替换旧文档）时递增，`version` 字段保留用于展示。
**Migration**: 新文档的 `version` = 旧文档的 `version` + 1。

### Requirement: 旧知识块标记为 superseded
**Reason**: `ChunkStatus.superseded` 状态移除。更新时旧知识块直接标记为 `deleted`。
**Migration**: 存量 `superseded` 数据迁移为 `deleted`。

### Requirement: 嵌入子文档级联更新
**Reason**: 级联更新逻辑随增量更新机制移除。更新时仅处理目标文档本身。
**Migration**: 如有级联更新需要，用户可逐个更新子文档。

### Requirement: /ingest 响应新增 warnings
**Reason**: `/ingest` 端点移除，无需迁移。
**Migration**: v1 上传接口保留 `duplicate_content` 等警告检测。
