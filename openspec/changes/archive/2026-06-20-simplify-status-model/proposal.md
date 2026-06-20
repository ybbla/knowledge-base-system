## Why

当前知识库系统的状态体系过于复杂：DocStatus 混入了未真正使用的 `pending`、ChunkStatus 代码中散落着枚举未定义的 `superseded`、ChunkIndexStatus 单独追踪索引进度却与 chunk 生命周期强耦合、AssetStatus 包含 4 个状态而实际只需 2 个。同时，入库任务管理（JobStatus 6 个状态 + 独立 UI）、增量更新（`mode=incremental` + superseded）、乐观锁（`expected_version` + PATCH 端点）增加了大量代码复杂度，却不提供对应的用户价值。现在需要做一次系统性的状态体系简化，统一概念模型，去除不必要的抽象层。

## What Changes

### 状态枚举简化
- DocStatus 保持 4 个值：`processing`、`active`、`failed`、`deleted`（移除 `pending`）— **BREAKING**
- ChunkStatus 简化为 2 个值：`active`、`deleted`（移除代码中散落的 `superseded`）— **BREAKING**
- AssetStatus 简化为 2 个值：`ready`、`failed`（移除 `pending`、`skipped`）— **BREAKING**
- 删除 `ChunkIndexStatus` 枚举及所有引用 — **BREAKING**

### Pydantic 模型字段精简
- `Document` 移除 `ingest_job_id`，保留 `version` 和 `previous_doc_id`（支撑版本历史）
- `KnowledgeChunk` 移除 `doc_version`、`index_status`、`indexed_at`、`index_error`、`ingest_job_id`

### API 端点变更
- 移除 `PATCH /api/v1/documents/{doc_id}`（乐观锁更新）
- 移除 `POST /api/v1/documents/{doc_id}/ingest`（单独触发入库）
- 移除 `GET/POST /api/v1/ingest/*` 全部入库任务管理端点
- `POST /api/v1/documents/upload` 新增同名文件检测 + 确认更新参数（来自 simplify-doc-upload-flow）
- 新增 `GET /api/v1/documents/{doc_id}/history` 版本历史查看（来自 simplify-doc-upload-flow）
- `GET /api/v1/chunks` 去掉 `index_status` 筛选参数

### 前端变更
- 删除整个 `ingestion.js`（入库任务管理界面）
- 页面导航去掉"入库管理"入口
- `chunks.js` 去掉索引状态下拉筛选和列
- `common.js` 的 `statusBadge()` 精简标签映射
- `documents.js` 添加更新按钮 + 同名检测弹窗（来自 simplify-doc-upload-flow）

### Pipeline 简化
- 移除 `JobStatus` 类（pending/processing/completed/canceled 生命周期）
- 移除增量更新分支（`mode=incremental` + superseded 标记）
- 移除 ChunkIndexStatus 的 pending→indexing→indexed→failed 流转
- 更新流程变为：软删除旧文档 + 旧 chunk → 创建新文档 → 入库新版本

## Capabilities

### New Capabilities
- `status-model`: 统一状态模型定义 — DocStatus（4 个值）、ChunkStatus（2 个值）、AssetStatus（2 个值），删除 ChunkIndexStatus
- `doc-update-flow`: 文档更新流程 — 上传同名检测、确认更新弹窗、软删除旧版本后创建新版本

### Modified Capabilities
- `document-ingestion`: 移除 JobStatus 生命周期和增量更新逻辑，简化为同步状态流转（processing → active | failed）
- `document-management-api`: 移除 PATCH /{doc_id}、POST /{doc_id}/ingest；新增 GET /{doc_id}/history；Document 字段增删
- `file-upload`: 上传接口新增同名检测和 `replace_doc_id`/`confirm_replace` 参数
- `chunk-management-api`: ChunkStatus 移除 superseded，移除 index_status 筛选参数和响应字段
- `asset-lifecycle`: AssetStatus 简化为 ready/failed，移除 pending/skipped
- `hybrid-retrieval`: 搜索过滤和索引恢复不再依赖 ChunkIndexStatus
- `milvus-indexing`: Milvus schema 不再维护 chunk 的 index_status 字段和 superseded 状态写入

### Removed Capabilities
- `ingest-job-management-api`: 入库任务管理功能整体移除，前端 ingestion.js 删除
- `optimistic-locking`: 乐观锁机制移除，PATCH endpoint 和 version conflict 错误码删除
- `document-incremental-update`: 增量更新逻辑移除，更新统一为"删旧+建新"

## Impact

- **后端核心**：`app/core/models.py`（枚举 + Pydantic）、`app/db/models.py`（DB 列）、`app/db/repositories/documents.py`、`app/db/repositories/chunks.py`、`app/core/deps.py`、`app/core/errors.py`
- **API 端点**：`app/api/v1/documents.py`、`app/api/v1/chunks.py`、`app/api/v1/ingest.py`（删除）、`app/api/v1/search.py`、`app/api/v1/services.py`
- **Ingestion Pipeline**：`ingestion/pipeline.py`（大幅简化）、`ingestion/recursive_loader.py`
- **索引层**：`indexing/milvus_vector.py`、`indexing/milvus_sparse.py`、`indexing/milvus_hybrid.py`、`indexing/memory_vector.py`、`indexing/memory_bm25.py`
- **前端**：`frontend/js/components/ingestion.js`（删除）、`documents.js`、`chunks.js`、`common.js`、`document-detail.js`、`search.js`、`app.js`、`index.html`
- **测试**：10+ 测试文件需同步调整

## 回滚计划

1. Git revert 本次变更的 commit
2. 数据库旧列（`ingest_job_id`、`doc_version`、`index_status`、`indexed_at`、`index_error`）代码层面先保留不删，仅忽略 r/w；如有问题恢复引用即可
3. 前端 `ingestion.js` 通过 git 恢复
4. API 端点恢复：git revert 即可恢复 PATCH、/{doc_id}/ingest、/api/v1/ingest/*
