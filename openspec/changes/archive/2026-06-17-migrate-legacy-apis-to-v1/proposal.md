## Why

当前前端已部分迁移到 `/api/v1`，但上传、入库提交和任务状态查询仍依赖 `/upload`、`/ingest`、`/ingest/{job_id}` 等旧接口，导致“入库任务”页面只能追踪浏览器本地记录，无法作为真实任务中心使用。

现在需要统一 v1 API 边界，让新文档上传后立即入库、已有文档重新入库、任务列表和任务详情都走一致的 v1 响应结构，减少前端兼容分支并为旧接口下线做好准备。

## What Changes

- 新增 v1 入库任务管理能力，通过 `/api/v1/ingest/jobs` 提供任务列表、任务详情、失败重试和可选取消能力。
- 修改 v1 文档管理能力，新增 `POST /api/v1/documents/upload`，替代旧 `POST /upload`，支持上传文件、创建文档并可选择立即提交入库。
- 修改 v1 文档创建和触发入库的契约，统一返回 `ingest_job_id`、任务状态元信息和前端可展示的文档摘要。
- 修改去重和增量入库规范，将旧 `/ingest` 中依赖 `source_hash` 的去重、更新检测能力迁移到 v1 文档上传和文档入库接口。
- 修改 MinIO 文件上传规范，将文件写入能力从旧 `/upload` 迁移到 `/api/v1/documents/upload`。
- 前端“文档管理”和“入库任务”页面停止调用旧接口，改为只调用 `/api/v1/**`。
- **BREAKING**：旧接口 `/upload`、`/ingest`、`/ingest/{job_id}` 不再作为前端业务入口；兼容期后将返回 `410 Gone` 或移除。
- 回滚计划：保留旧接口实现一个兼容周期，前端 API 封装保留旧方法但不再调用；如果 v1 上传或任务接口出现阻塞，可临时将前端上传流程切回旧封装，同时保留新接口代码和测试以便修复后恢复。

## Capabilities

### New Capabilities

- `ingest-job-management-api`: 定义 `/api/v1/ingest/jobs` 的任务列表、任务详情、重试、取消和任务展示字段契约。

### Modified Capabilities

- `document-management-api`: 新增 v1 文件上传创建文档接口，并统一创建后入库、已有文档触发入库的返回结构。
- `document-deduplication`: 将上传和入库阶段的 `source_hash` 去重要求迁移到 v1 上传、创建和入库接口。
- `document-incremental-update`: 将旧 `/ingest` 的增量更新输入模型和行为迁移到 `/api/v1/documents/{doc_id}/ingest`。
- `minio-storage`: 将文件上传写入 MinIO 的入口从 `/upload` 更新为 `/api/v1/documents/upload`。

## Impact

- 后端 API：新增 `app/api/v1/ingest.py` 或等价 v1 路由；增强 `app/api/v1/documents.py`；旧 `app/api/upload.py`、`app/api/ingest.py` 进入兼容/废弃路径。
- 前端 API 封装：移除业务页面对 `API.uploadFile`、`API.submitIngest`、`API.getIngestJob` 的调用，新增 v1 上传和任务接口封装。
- 前端页面：文档上传弹窗继续展示“开始上传并入库”；入库任务页改为后端任务列表驱动，不再依赖 `localStorage.kb_job_ids`。
- 存储和索引：复用现有上传存储、文档仓储、入库管线、向量索引和 BM25 索引能力，不引入新的外部依赖。
- 测试：需要覆盖上传后立即入库、已有文档入库、任务列表/详情、失败重试、旧接口废弃提示和重复文档处理。
