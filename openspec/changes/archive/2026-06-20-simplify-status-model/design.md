## Context

当前知识库系统经过多轮迭代，积累了多层抽象：DocStatus（4 个值，`pending` 已移除）、ChunkStatus（枚举 2 个值但代码中有裸字符串 `"superseded"`）、ChunkIndexStatus（4 个值）、AssetStatus（4 个值）、JobStatus（6 个值裸字符串）。这些状态分散在 Pydantic 模型、SQLAlchemy 模型、API 端点、前端 UI 和索引层中。

**已提前实现**（来自 simplify-doc-upload-flow）：
- Document Pydantic 已移除 `ingest_job_id`，已有 `previous_doc_id` + `error_message`
- DocumentRepository 已无 `ingest_job_id` 读写，`find_similar_by_filename()` / `get_version_history()` 已就绪
- `POST /api/v1/documents/upload` 同名检测 + `replace_doc_id`/`confirm_replace` 已实现
- `POST /{doc_id}/ingest` 已删除，`GET /{doc_id}/history` 已实现
- DbDocument 的 `ingest_job_id` 列已有 deprecated 注释

**仍待实施**（本次 change 核心工作）：
1. ChunkIndexStatus 全链路删除：枚举 → Pydantic → DB repo → API → Pipeline → 索引层 → 前端
2. AssetStatus 简化：`pending`/`skipped` → 删除，默认值 `pending` → `ready`
3. JobStatus 移除 + Pipeline 简化：去掉 6 状态任务生命周期 + incremental 分支 + superseded
4. 乐观锁移除：PATCH 端点 + `VersionConflictError` + `update()` 的 version 检查
5. 裸字符串 `"superseded"` 全部替换为 `"deleted"`
6. 前端：删除 `ingestion.js` + 去 `index_status`/`superseded` 引用 + statusBadge 精简

**当前模型字段**（关键部分）：
- `Document`：`version`、`status`、`previous_doc_id`、`error_message`（`ingest_job_id` 已移出 Pydantic）
- `KnowledgeChunk`：`doc_version`、`status`、`index_status`、`indexed_at`、`index_error`、`ingest_job_id`
- `Asset`：`status`（默认 `pending`）、`extracted_text`、`error_message`

## Goals / Non-Goals

**Goals:**
- 将 DocStatus 稳定为 4 个值：`processing`、`active`、`failed`、`deleted`
- 将 ChunkStatus 收敛为 2 个值：`active`、`deleted`（彻底消除 superseeded）
- 将 AssetStatus 简化为 2 个值：`ready`、`failed`
- 删除 ChunkIndexStatus 枚举及其在整个技术栈中的引用
- 删除 JobStatus 和整个 ingestion 任务管理子系统
- 删除增量更新逻辑（`mode=incremental` + superseeded 标记）
- 删除乐观锁（PATCH endpoint + `expected_version`）
- 保留 `version` 和 `previous_doc_id` 字段用于版本历史展示和版本链追踪
- 数据库旧列代码层面忽略但保留（`ingest_job_id`、`doc_version`、`index_status`、`indexed_at`、`index_error`），避免数据库迁移风险

**Non-Goals:**
- 不实现复杂的版本对比和回滚功能
- 不修改嵌入文档的 `parent_doc_id`、`root_doc_id` 逻辑
- 不改变软删除/恢复的核心机制（只调整内部状态名和过滤条件）
- 不执行 DDL 迁移（旧列保留，仅代码层面停止引用）

## Decisions

### Decision 1: DocStatus 保留 `processing`，移除 `pending`

**选择**：4 状态模型 — `processing` → `active` | `failed`（`deleted` 为独立软删除分支）。

**理由**：
- `pending` 在当前代码中从未被实际赋值使用
- 文档创建即进入 `processing`（解析/抽取/索引进行中），用户和前端需要这个中间状态区分"已入库可搜索"和"还在处理中"
- 文档创建时默认值为 `processing`

**替代方案**：只留 3 个（去掉 processing）。拒绝理由：文档创建瞬间不可能是 active，搜索会搜到空文档。

### Decision 2: ChunkStatus 移除 `superseded`

**选择**：枚举仅定义 `active` 和 `deleted`，更新时旧 chunk 直接标记 `deleted`。

**理由**：
- 当前枚举（models.py:41-43）实际上只定义了 `active` 和 `deleted`，`superseded` 是裸字符串使用
- 语义上 "superseded" 和 "deleted" 对检索系统效果完全相同（都不应被搜到）
- 简化状态流转，减少一个分支

**替代方案**：在枚举中正式定义 `superseded`。拒绝理由：增加概念但无实际区分价值。

### Decision 3: 删除 ChunkIndexStatus

**选择**：完全移除 `ChunkIndexStatus`（pending/indexing/indexed/failed），KnowledgeChunk 不再有 `index_status` 字段。

**理由**：
- chunk 创建后立即入索引入队，不需要 pending 状态
- chunk 删除后从索引移除，不需要单独追踪
- Milvus/BM25 索引层已有自己的状态和错误处理（insert/delete 操作本身返回成功/失败）
- 索引失败直接让文档进入 failed 状态，通过 `error_message` 传达原因
- 减少 12 个文件的引用、1 个 DB 列、前端一整列 + 筛选器

**替代方案**：保留但简化（如去掉 indexing 中间态）。拒绝理由：即使简化到 2 个值，仍需要维护额外的 DB 列和状态同步逻辑，开销大于收益。

### Decision 4: AssetStatus 简化为 `ready` 和 `failed`

**选择**：2 状态模型，默认值为 `ready`。

**理由**：
- `pending` 状态在实际流程中几乎不可见——资源解析后要么成功（ready）要么失败（failed）
- `skipped` 可以通过不创建 Asset 记录来表达（跳过就不记录），无需额外状态

**替代方案**：保留 4 个。拒绝理由：4 个状态中实际只用到了 2 个。

### Decision 5: 删除 JobStatus 和 ingestion 任务管理

**选择**：移除 `pipeline.py` 的 `JobStatus` 类、`/api/v1/ingest/*` 端点、前端 `ingestion.js`。

**理由**：
- 文档状态（DocStatus）已经充分表达了处理进度
- JobStatus 的 6 个状态（accepted/pending/processing/completed/failed/canceled）和 DocStatus 高度重叠
- 去掉任务管理减少了整个前端页面 + 一套 API 端点 + 后台 Job 生命周期管理

**替代方案**：保留但简化。拒绝理由：用户真正需要的是"文档状态"，不是"任务状态"。

### Decision 6: 删除增量更新，统一为"删旧 + 建新"

**选择**：移除 `mode=incremental` 参数和 ChunkStatus.superseded 标记逻辑。更新流程变为：软删除旧文档及其 chunk → 创建新文档（`previous_doc_id` 指向旧文档）→ 完整入库。

**理由**：
- 增量更新（保留旧 chunk 标记为 superseded）增加了复杂的 chunk 级别 diff 逻辑
- "全量重建"更简单、更可靠，且对用户透明
- `previous_doc_id` 版本链保留了历史可追溯性

**替代方案**：保留增量更新能力。拒绝理由：复杂度太高，用户价值有限。

### Decision 7: 删除乐观锁和 PATCH 端点

**选择**：移除 `PATCH /api/v1/documents/{doc_id}`、`expected_version` 参数、`DOCUMENT_VERSION_CONFLICT` 错误码。

**理由**：
- 当前并发写入场景极少（主要是单用户上传）
- 更新流程已改为"删旧建新"，不再有原地更新的并发冲突风险
- `version` 字段保留用于展示版本号，但不再用于乐观锁检查

**替代方案**：保留 PATCH 用于元数据编辑。拒绝理由：当前没有前端元数据编辑界面，可后续按需恢复。

### Decision 8: 数据库向后兼容

**选择**：所有要删除的 DB 列（`ingest_job_id`、`doc_version`、`index_status`、`indexed_at`、`index_error`）在 SQLAlchemy 模型中保留列定义但代码层不再读写。等稳定运行后再执行 DDL 删除。

**理由**：
- 避免数据库迁移风险
- 如有问题可快速回滚代码版本
- 旧数据不受影响

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| ChunkIndexStatus 删除后索引失败无法细粒度追踪 | 索引失败直接标记 doc 为 failed + error_message，问题定位仍清晰 |
| 旧数据中存量的 `superseded`/`pending` chunk | 加一条数据迁移：存量 superseded → deleted，存量 index_status=indexing → 视为 indexed |
| 前端删除 ingestion.js 后用户无法查看历史任务 | 非目标——任务信息不再维护，文档状态已充分表达进度 |
| `index_status` 字段从 API 响应中移除破坏前端兼容 | 前端同步修改，不再读取该字段 |
| 删除 JobStatus 后 pipeline 错误处理链路变化 | pipeline 简化为同步异常处理，异常直接设置 doc.failed |

## Migration Plan

1. 修改 `app/core/models.py` — 枚举和 Pydantic 字段
2. 修改 `app/db/models.py` — DB 列（旧列保留）
3. 修改 `app/db/repositories/` — 仓库层适配
4. 修改 `app/api/v1/` — API 端点增删
5. 简化 `ingestion/pipeline.py` — 移除 JobStatus
6. 修改索引层 — 去掉 index_status 字段
7. 修改前端 — 删除 ingestion.js + 精简其他组件
8. 运行测试验证无回归
9. 数据迁移脚本（存量 superseded → deleted）

**回滚策略**：
- 所有旧 DB 列仍在，代码回滚后即可恢复读写
- 前端 ingestion.js 通过 git 恢复
- API 端点 git revert 即可恢复

## Open Questions

1. 存量 `superseded` chunk 是否需要在本次 change 中迁移为 `deleted`？（建议在 migration 脚本中处理）
2. `Asset.created_at` / `Asset.updated_at` 是否保留？（当前 design 不提，由 asset-lifecycle spec 决定）
