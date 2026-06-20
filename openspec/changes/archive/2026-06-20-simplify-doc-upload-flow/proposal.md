## Why

当前文档上传流程过于复杂，存在冗余的状态和任务管理。`pending` 状态实际上从未被使用（文档上传后立即进入 `processing`），`ingest_job_id` 引入了不必要的任务追踪概念。同时，用户需要一个简单清晰的文档更新体验，能够检测同名文件并提示是否更新。

## What Changes

- 移除 `DocStatus.pending` 状态
- 移除 `ChunkStatus.superseded` 状态
- 从 `Document` 模型中移除 `ingest_job_id` 字段
- 新增 `Document.previous_doc_id` 字段用于版本历史追踪
- 新增 `Document.error_message` 字段用于展示失败原因
- 上传接口新增同名文件检测和确认更新流程
- 移除 `/api/v1/documents/{doc_id}/ingest` 重新处理接口
- 文档列表新增"更新"按钮，支持直接更新现有文档
- 新增版本历史查看接口

## Capabilities

### New Capabilities
- `doc-update-flow`: 文档更新流程（自动检测同名 + 手动更新按钮）
- `doc-version-history`: 文档版本历史查看

### Modified Capabilities
- `document-management-api`: 更新文档管理 API，移除重新处理接口，新增版本历史接口
- `file-upload`: 更新文件上传接口，支持同名检测和确认更新
- `document-ingestion`: 更新文档入库流程，简化状态流转

## Impact

- 后端代码：`app/core/models.py`、`app/db/models.py`、`app/db/repositories/documents.py`、`app/api/v1/documents.py`
- 前端代码：`frontend/js/components/documents.js`
- 数据库：新增字段（向后兼容，旧字段先保留）
- API：部分接口字段变更，移除一个接口

## 回滚计划

如果出现问题，可以：
1. 恢复移除的状态和字段
2. 恢复重新处理接口
3. 回滚前端改动
