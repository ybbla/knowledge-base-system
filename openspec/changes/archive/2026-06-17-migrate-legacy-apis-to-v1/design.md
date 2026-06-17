## Context

当前系统已有 `/api/v1/documents`、`/api/v1/chunks`、`/api/v1/search` 和 `/api/v1/health`，但文件上传、入库提交和任务查询仍保留在旧接口 `/upload`、`/ingest`、`/ingest/{job_id}`。前端文档上传弹窗通过旧接口串联“上传文件”和“提交入库”，入库任务页通过浏览器 `localStorage` 保存 job id 后逐个调用旧任务查询接口，因此无法展示服务端完整任务列表。

本次变更需要把前端业务入口统一到 `/api/v1`，并保持“上传后立即入库”“已有文档重新入库”“任务状态可追踪”的用户体验。实现应复用现有 `ingestion_pipeline`、`document_repo`、`chunk_store`、MinIO/本地上传逻辑和统一 v1 响应结构。

受影响模块包括：

- `knowledge_base_system/app/api/v1/documents.py`
- `knowledge_base_system/app/api/v1/ingest.py` 或新增等价 v1 子路由
- `knowledge_base_system/app/api/v1/__init__.py`
- `knowledge_base_system/app/api/upload.py`
- `knowledge_base_system/app/api/ingest.py`
- `knowledge_base_system/app/core/deps.py`
- `knowledge_base_system/ingestion/pipeline.py`
- `frontend/js/api.js`
- `frontend/js/components/documents.js`
- `frontend/js/components/ingestion.js`
- 相关 v1 API、上传、入库任务测试

## Goals / Non-Goals

**Goals:**

- 新增 v1 文件上传入口，支持上传文件、创建 Document、可选立即提交入库任务。
- 新增 v1 入库任务管理入口，支持任务列表、任务详情、失败重试和可选取消。
- 前端业务页面停止调用旧 `/upload`、`/ingest`、`/ingest/{job_id}`。
- 入库任务页改为服务端数据驱动，支持刷新、轮询、状态筛选和失败原因展示。
- 保留旧接口一个兼容周期，降低回滚风险。

**Non-Goals:**

- 不重写解析器、语义抽取、embedding、Faiss/BM25/Milvus 索引实现。
- 不引入新的任务队列或外部调度系统。
- 不改变知识块管理、检索接口的核心契约。
- 不要求旧接口立即物理删除；本变更先完成 v1 替代和废弃标记。

## Decisions

### Decision 1: 上传创建文档使用 `POST /api/v1/documents/upload`

新增 multipart v1 接口接收 `file`、`title`、`category`、`ingest_after_create` 和 `mode`。接口内部复用旧上传逻辑中的 hash 计算、MinIO 写入和本地回退逻辑，但返回 v1 `APIResponse`，并在非重复文档时创建 Document。

理由：前端“上传文档”属于文档管理能力，而不是独立文件服务；把上传入口放在 `/api/v1/documents/upload` 可以让上传、创建、去重、立即入库在同一契约内完成。

替代方案：新增 `/api/v1/uploads` 再由前端调用 `/api/v1/documents`。该方案更通用，但会让前端继续维护两步链路，不利于保持“上传并入库”的简单体验。

### Decision 2: 入库任务使用独立 v1 资源 `/api/v1/ingest/jobs`

新增任务列表和详情接口，统一返回 `job_id`、`doc_id`、`doc_title`、`mode`、`status`、`stage`、`progress`、`chunk_count`、`asset_count`、`error`、`created_at`、`started_at`、`finished_at` 等字段。列表接口支持 `status`、`doc_id`、`keyword`、分页和排序。

理由：任务是跨文档的操作记录，前端“入库任务”页面需要服务端完整列表，而不是单个文档详情的附属字段。

替代方案：只在文档详情上展示最近一次入库任务。该方案不能支撑任务中心、失败重试和全局运维视角。

### Decision 3: 任务数据先复用现有 `ingestion_pipeline`，必要时补轻量查询适配

实现优先从现有入库管线的 job 存储读取任务。若当前管线只支持 `get_job(job_id)`，则补充 `list_jobs(...)` 或在 v1 层增加只读适配，避免引入数据库迁移作为首个版本的前置条件。

理由：本次变更目标是接口统一和前端迁移，任务持久化可以作为后续增强。内存模式和 PostgreSQL 模式都应先保持可用。

替代方案：新增 `ingest_jobs` 表并完全持久化任务。该方案更完整，但会扩大迁移范围，且需要补历史任务迁移策略。

### Decision 4: 旧接口进入兼容期，不再作为前端入口

旧 `/upload`、`/ingest`、`/ingest/{job_id}` 暂时保留实现，添加废弃响应头和日志；前端移除业务调用。确认 v1 路径稳定后，再将旧接口切换为 `410 Gone` 或移除路由。

理由：上传和入库属于高价值路径，保留短期回滚能力可以降低迁移风险。

替代方案：立即删除旧接口。该方案会强制暴露所有兼容问题，不适合当前存在较多前端改动的工作区。

### Decision 5: 前端展示以任务阶段和可操作状态为中心

入库任务页从 `GET /api/v1/ingest/jobs` 拉取任务，展示状态、阶段、进度、知识块数、资源数、错误摘要和文档跳转；进行中任务自动轮询，失败任务提供重试。上传弹窗在 v1 上传成功并返回 `ingest_job_id` 后提示“已提交入库任务”，并提供查看任务入口。

理由：用户关心的是任务是否成功、卡在哪个阶段、失败后能否处理；这比仅展示本地保存的 job id 更可解释。

## Risks / Trade-offs

- [Risk] 当前 `ingestion_pipeline` 如果没有全量任务列表能力，v1 任务页可能只能展示进程内任务。  
  Mitigation：先实现 `list_jobs` 的进程内适配，并在响应中明确只展示当前服务实例可见任务；后续再引入持久化任务表。

- [Risk] 大文件上传经 v1 包装后可能增加内存占用。  
  Mitigation：沿用旧上传接口的分块 hash、MinIO 分片上传和本地流式写入方式，不把完整文件读入内存。

- [Risk] 文件名、source_uri、错误信息直接展示可能带来安全问题。  
  Mitigation：后端只返回必要字段，前端继续使用 HTML 转义；日志避免记录敏感凭据或完整外部 URL 查询参数。

- [Risk] 重复文档处理语义从旧接口迁移到 v1 后，前端可能误判成功/失败。  
  Mitigation：v1 上传对重复内容返回统一结构，包含 `duplicate=true`、`existing_doc_id` 和可展示提示；测试覆盖重复上传。

- [Risk] 旧接口兼容期会短暂增加维护成本。  
  Mitigation：旧接口只保留现有行为和废弃提示，不增加新能力；任务完成后集中删除。

## Migration Plan

1. 新增 v1 入库任务路由并挂载到 `/api/v1/ingest/jobs`。
2. 新增 `POST /api/v1/documents/upload`，复用现有上传存储逻辑并返回 v1 响应。
3. 增强 `POST /api/v1/documents/{doc_id}/ingest` 的返回字段，使前端可直接记录和展示任务。
4. 前端 `api.js` 新增 v1 上传和任务接口封装，标记旧方法为仅兼容。
5. 文档上传弹窗切到 v1 上传接口，保留“开始上传并入库”的展示。
6. 入库任务页切到 v1 任务列表和详情，不再读写 `localStorage.kb_job_ids` 作为主数据源。
7. 为旧接口添加废弃响应头、日志和测试，确认前端无调用。
8. 回滚时只需将前端上传和任务查询封装切回旧方法；后端旧接口在兼容期内保持可用。

## Open Questions

- 入库任务是否需要在本次变更中持久化到 PostgreSQL，还是先使用现有进程内任务存储？
- `cancel` 是否只支持 `pending` 任务，还是需要为 `processing` 任务设计协作式取消点？
- 旧接口兼容期长度由发布节奏决定，建议至少覆盖一个前端发布周期。
