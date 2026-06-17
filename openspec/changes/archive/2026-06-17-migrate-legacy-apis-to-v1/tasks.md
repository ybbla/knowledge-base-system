## 1. 后端 v1 入库任务接口

- [x] 1.1 新增 `/api/v1/ingest/jobs` 路由模块，并挂载到 v1 router
- [x] 1.2 为入库任务实现统一序列化函数，返回 `job_id`、`doc_id`、`doc_title`、`mode`、`status`、`stage`、`progress`、`chunk_count`、`asset_count`、`error` 和时间字段
- [x] 1.3 为现有入库管线补充 `list_jobs` 查询能力或 v1 只读适配
- [x] 1.4 实现 `GET /api/v1/ingest/jobs`，支持分页、状态、文档、关键词和模式筛选
- [x] 1.5 实现 `GET /api/v1/ingest/jobs/{job_id}`，不存在时返回 v1 统一 404 错误
- [x] 1.6 实现 `POST /api/v1/ingest/jobs/{job_id}/retry`，仅允许失败任务重试
- [x] 1.7 评估并实现 `POST /api/v1/ingest/jobs/{job_id}/cancel` 的 pending 任务取消能力，processing 任务不可取消时返回 409

## 2. 后端 v1 文档上传和入库

- [x] 2.1 从旧 `/upload` 抽取可复用的 hash 计算、MinIO 写入和本地回退辅助函数
- [x] 2.2 实现 `POST /api/v1/documents/upload` multipart 接口，支持 `file`、`title`、`category`、`ingest_after_create` 和 `mode`
- [x] 2.3 在 v1 上传接口中完成 `source_hash` 去重，重复活跃文档返回 `duplicate=true` 和 `existing_doc_id`
- [x] 2.4 在 v1 上传接口中创建 Document 记录，并在 `ingest_after_create=true` 时提交入库任务
- [x] 2.5 增强 `POST /api/v1/documents/{doc_id}/ingest` 返回结构，补充任务状态和前端展示所需字段
- [x] 2.6 统一 v1 创建文档、上传文档、触发入库的错误码和响应结构
- [x] 2.7 为旧 `/upload`、`/ingest`、`/ingest/{job_id}` 添加明确废弃响应头和日志，不再新增能力

## 3. 前端 API 封装

- [x] 3.1 在 `frontend/js/api.js` 新增 `uploadDocument`、`listIngestJobs`、`getIngestJobV1`、`retryIngestJob` 和 `cancelIngestJob` 封装
- [x] 3.2 将旧 `uploadFile`、`submitIngest`、`getIngestJob` 标记为兼容方法，并确认业务页面不再调用
- [x] 3.3 统一前端对 v1 `APIResponse`、分页响应和错误响应的解析

## 4. 前端页面切换和展示

- [x] 4.1 将文档上传弹窗切换到 `POST /api/v1/documents/upload`
- [x] 4.2 保留“开始上传并入库”的展示流程，上传成功后显示 `ingest_job_id` 并提供查看任务入口
- [x] 4.3 将入库任务页数据源切换到 `GET /api/v1/ingest/jobs`
- [x] 4.4 移除入库任务页对 `localStorage.kb_job_ids` 的主数据依赖
- [x] 4.5 为入库任务页增加状态筛选、刷新、自动轮询、失败原因展示和文档跳转
- [x] 4.6 为失败任务增加重试按钮，为可取消任务增加取消按钮
- [x] 4.7 确认文档列表和文档详情中的“重新入库”仍走 `POST /api/v1/documents/{doc_id}/ingest`

## 5. 测试和验证

- [x] 5.1 添加 v1 上传接口测试：新文件上传、不立即入库、立即入库、重复文件、MinIO 回退
- [x] 5.2 添加 v1 入库任务接口测试：任务列表、任务详情、不存在任务、失败任务重试、不可重试状态
- [x] 5.3 添加已有文档入库测试：`mode=incremental`、`mode=force`、文档不存在
- [x] 5.4 添加旧接口废弃测试：响应头、兼容行为和前端无业务调用
- [x] 5.5 添加前端调用检查，确认 `documents.js` 和 `ingestion.js` 不再调用旧上传/入库接口
- [x] 5.6 运行相关 pytest 测试和前端静态调用验证，记录任何未覆盖的风险

## 6. 收尾和迁移确认

- [x] 6.1 更新 API 文档或接口审计文档，列出旧接口到 v1 接口的迁移关系
- [x] 6.2 确认入库任务页在清空浏览器缓存后仍能展示服务端任务列表
- [x] 6.3 确认回滚路径可用：旧接口兼容期内前端封装可临时切回旧链路
- [x] 6.4 整理后续工作：任务持久化、processing 任务协作式取消、旧接口最终 `410 Gone` 或移除
