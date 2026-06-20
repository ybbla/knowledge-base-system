# Optimistic Locking (Delta)

## REMOVED Requirements

### Requirement: 文档更新时乐观锁检查
**Reason**: 乐观锁机制整体移除。更新流程已改为"软删除旧文档 + 创建新文档"，不再有原地更新的并发冲突场景。`version` 字段保留用于展示版本号，但不再用于并发控制。
**Migration**: `PATCH /api/v1/documents/{doc_id}` 端点一并移除。元数据变更（如标题、分类）如有需要可后续单独设计轻量级编辑接口。

### Requirement: VersionConflictError 异常类型
**Reason**: 随乐观锁机制移除。
**Migration**: `VersionConflictError` 类从 `app/core/errors.py` 中删除。

### Requirement: DocumentRepository.create 先检查后插入
**Reason**: 创建时的 upsert 检查逻辑保留但简化——仅做 `source_hash` 重复检查，不再涉及 version 冲突。
**Migration**: `DuplicateDocumentError` 保留，用于处理相同 `source_hash` 的重复创建请求。

### Requirement: DuplicateDocumentError 异常类型
**Reason**: 不在此次移除范围内——重复文档检测仍然需要。
**Migration**: `DuplicateDocumentError` 继续保留使用。
