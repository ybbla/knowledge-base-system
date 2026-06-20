# Ingest Job Management API (Delta)

## REMOVED Requirements

### Requirement: 入库任务列表支持分页和筛选
**Reason**: 入库任务管理功能整体移除。文档状态（DocStatus）已充分表达处理进度，不再需要独立的任务追踪概念。
**Migration**: 用户通过文档列表页面查看文档状态（processing/active/failed）来了解进度。重试功能通过重新上传文件实现。

### Requirement: 入库任务列表项包含前端展示字段
**Reason**: 随任务列表接口一并移除。
**Migration**: 前端展示字段（chunk_count、asset_count 等）已存在于文档详情接口中。

### Requirement: 入库任务详情可被查询
**Reason**: 随任务管理功能整体移除。
**Migration**: 使用 `GET /api/v1/documents/{doc_id}` 查看文档处理状态和错误信息。

### Requirement: 失败任务支持重试
**Reason**: 随任务管理功能整体移除。
**Migration**: 用户通过重新上传文件来达到重试效果。

### Requirement: 入库任务可选支持取消
**Reason**: 随任务管理功能整体移除。
**Migration**: 不再支持取消正在处理的任务，但可通过删除文档来移除不需要的内容。
