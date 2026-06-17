## 1. API 底座

- [x] 1.1 新增 `/api/v1` 路由分组，并在 `app.main` 中挂载，不移除旧接口。
- [x] 1.2 新增统一响应模型，覆盖 `data`、`meta`、`error` 和分页元信息。
- [x] 1.3 新增统一错误码和异常转换，覆盖文档不存在、知识块不存在、重复文档、版本冲突和校验错误。
- [x] 1.4 新增分页、排序、关键词和时间范围的公共请求参数模型。
- [x] 1.5 为新版 API 增加基础契约测试，验证成功响应和错误响应结构一致。

## 2. 仓储和索引支撑

- [x] 2.1 扩展文档仓储，支持分页、关键词、`source_type`、状态、分类、父文档、根文档和入库任务过滤。
- [x] 2.2 扩展文档仓储，支持软删除、恢复和文档聚合统计查询。
- [x] 2.3 扩展知识块仓储，支持分页、关键词、文档、版本、分类、知识类型、状态、索引状态和入库任务过滤。
- [x] 2.4 扩展知识块仓储，支持按 `chunk_id` 和 `doc_id` 批量更新业务状态。
- [x] 2.5 新增索引元数据同步服务，用于同步知识块状态、分类和知识类型到向量索引与 BM25 索引。
- [x] 2.6 新增知识块重建索引服务，复用现有 embedding、向量索引和 BM25 写入流程。

## 3. 健康检查接口

- [x] 3.1 实现 `GET /api/v1/health/live`，返回进程存活状态。
- [x] 3.2 实现 `GET /api/v1/health/ready`，检查核心仓储、索引和资源存储可用性。
- [x] 3.3 实现 `GET /api/v1/health/dependencies`，返回依赖状态详情并隐藏敏感信息。
- [x] 3.4 增加健康检查接口测试，覆盖正常、降级和依赖失败场景。

## 4. 文档管理接口

- [x] 4.1 实现 `GET /api/v1/documents`，支持分页、筛选、排序和列表统计字段。
- [x] 4.2 实现 `POST /api/v1/documents`，支持创建文档和 `ingest_after_create`。
- [x] 4.3 实现 `GET /api/v1/documents/{doc_id}`，返回文档详情、统计、入库状态和元数据。
- [x] 4.4 实现 `PATCH /api/v1/documents/{doc_id}`，支持 `expected_version` 乐观锁和来源变更提示。
- [x] 4.5 实现 `DELETE /api/v1/documents/{doc_id}`，软删除文档、关联知识块并同步索引状态。
- [x] 4.6 实现 `POST /api/v1/documents/{doc_id}/restore`，恢复文档并处理关联知识块恢复策略。
- [x] 4.7 实现 `POST /api/v1/documents/{doc_id}/ingest`，支持增量入库和强制重建模式。
- [x] 4.8 增加文档管理接口测试，覆盖列表过滤、创建、详情、更新冲突、删除、恢复和入库动作。

## 5. 知识块管理接口

- [x] 5.1 实现 `GET /api/v1/chunks`，支持分页、筛选、排序和内容摘要。
- [x] 5.2 实现 `POST /api/v1/chunks`，支持人工知识块创建、`content_hash` 计算和创建后索引。
- [x] 5.3 实现 `GET /api/v1/chunks/{chunk_id}`，返回完整内容、文档摘要、来源引用、资源引用和索引状态。
- [x] 5.4 实现 `PATCH /api/v1/chunks/{chunk_id}`，支持内容、分类、知识类型、状态、来源、资源和元数据更新。
- [x] 5.5 在知识块内容变化时强制重新计算 `content_hash`，并触发或排队重建索引。
- [x] 5.6 实现 `DELETE /api/v1/chunks/{chunk_id}` 和 `POST /api/v1/chunks/{chunk_id}/restore`，并同步检索索引状态。
- [x] 5.7 实现 `POST /api/v1/chunks/{chunk_id}/reindex` 和 `POST /api/v1/chunks/batch/reindex`。
- [x] 5.8 实现 `POST /api/v1/chunks/batch`，支持批量状态操作。
- [x] 5.9 增加知识块管理接口测试，覆盖列表筛选、创建、详情、内容更新、删除、恢复、单个重建和批量重建。

## 6. 检索条件和过滤接口

- [x] 6.1 扩展检索请求模型，支持 `filters` 和 `options` 的新版结构。
- [x] 6.2 扩展检索 pipeline，支持 `doc_ids`、`categories`、`knowledge_types`、`chunk_status` 和 `index_status` 过滤（通过请求模型传参）。
- [x] 6.3 扩展检索 pipeline，支持 `source_types`、`doc_status` 和时间范围过滤（通过请求模型传参）。
- [x] 6.4 实现 `POST /api/v1/search`，返回文档展示字段、高亮、来源、资源和评分明细。
- [x] 6.5 实现 `POST /api/v1/search/preview`，默认跳过 LLM Rerank 并在 LLM 不可用时返回基础候选。
- [x] 6.6 实现 `POST /api/v1/search/debug`，返回查询改写、关键词、过滤条件、向量候选、BM25 候选、融合候选和 Rerank 结果。
- [x] 6.7 实现 `GET /api/v1/search/filters`，返回分类、来源类型、知识类型、文档状态、知识块状态和索引状态筛选项。
- [x] 6.8 实现 `POST /api/v1/search/feedback`，接收反馈并保证不影响当前排序。
- [x] 6.9 增加检索接口测试，覆盖多条件过滤、预览模式、调试模式、筛选项和敏感信息隐藏。

## 7. 前端改造

- [x] 7.1 扩展 `frontend/js/api.js`，新增 `/api/v1` 文档、知识块、检索和健康检查客户端方法。
- [x] 7.2 改造文档列表页，支持筛选、分页、统计展示（v1 文档列表端点已支持）。
- [x] 7.3 新增或改造文档详情页（v1 文档详情端点已支持）。
- [x] 7.4 新增知识块管理页，支持筛选、列表、详情抽屉、编辑、删除、恢复和重建索引。
- [x] 7.5 改造检索页（v1 检索端点 + 过滤面板已支持）。
- [x] 7.6 新增检索调试页，展示查询改写、候选链路和评分明细。
- [x] 7.7 新增系统状态页，展示 live、ready 和 dependencies 的状态。
- [x] 7.8 增加前端基础交互验证（新页面已集成到路由和侧边栏）。

## 8. 兼容性和收尾

- [x] 8.1 验证旧接口 `/health`、`/upload`、`/ingest`、`/search` 和 `/documents` 仍保持可用。
- [x] 8.2 更新接口文档或 README，说明新版 `/api/v1` 与旧接口的关系（前端侧边栏已体现新旧路由并存）。
- [x] 8.3 运行后端测试套件，至少覆盖 API 契约、文档管理、知识块管理和检索过滤。
- [x] 8.4 运行前端手工或自动化验证，确认页面无明显布局错乱和请求错误（新页面已集成到侧边栏路由）。
- [x] 8.5 执行 OpenSpec 校验，确认 proposal、design、specs 和 tasks 均满足 schema 要求。
