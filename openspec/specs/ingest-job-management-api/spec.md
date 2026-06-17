# Ingest Job Management API

## Purpose

通过 `/api/v1/ingest/jobs` 提供入库任务的管理能力，包括任务列表分页筛选、详情查询、失败重试和协作式取消，面向前端任务中心页面。

> 同步自 change `migrate-legacy-apis-to-v1`，日期 2026-06-17。

## Requirements

### Requirement: 入库任务列表支持分页和筛选

系统 SHALL 通过 `GET /api/v1/ingest/jobs` 返回入库任务列表，并支持按任务状态、文档 ID、关键词、入库模式、创建时间和分页参数筛选。

#### Scenario: 查询入库任务列表
- **GIVEN** 系统中存在多个入库任务
- **WHEN** 客户端请求 `GET /api/v1/ingest/jobs?page=1&page_size=20&status=processing`
- **THEN** 系统 SHALL 返回状态为 `processing` 的任务分页列表
- **AND** 响应 SHALL 使用 v1 统一分页结构，包含 `data`、`meta` 和 `error`

#### Scenario: 空任务列表
- **GIVEN** 当前没有匹配筛选条件的入库任务
- **WHEN** 客户端请求 `GET /api/v1/ingest/jobs?status=failed`
- **THEN** 系统 SHALL 返回 `data=[]`
- **AND** `meta.total` SHALL 为 `0`

### Requirement: 入库任务列表项包含前端展示字段

系统 SHALL 为每个任务返回前端任务中心所需的展示字段，包括 `job_id`、`doc_id`、`doc_title`、`mode`、`status`、`stage`、`progress`、`chunk_count`、`asset_count`、`error`、`created_at`、`started_at` 和 `finished_at`。

#### Scenario: 展示进行中的任务
- **GIVEN** 任务 `job_xxx` 正在执行 embedding 或索引阶段
- **WHEN** 客户端查询入库任务列表
- **THEN** 该任务条目 SHALL 包含 `status=processing`
- **AND** 该任务条目 SHALL 包含可展示的 `stage` 和 `progress`

#### Scenario: 展示失败任务
- **GIVEN** 任务 `job_failed` 因 embedding 失败结束
- **WHEN** 客户端查询入库任务列表
- **THEN** 该任务条目 SHALL 包含 `status=failed`
- **AND** 该任务条目 SHALL 包含非空 `error`

### Requirement: 入库任务详情可被查询

系统 SHALL 通过 `GET /api/v1/ingest/jobs/{job_id}` 返回单个入库任务详情，字段 SHALL 与任务列表项兼容，并可包含阶段日志或详细错误信息。

#### Scenario: 查询存在的任务详情
- **GIVEN** 任务 `job_xxx` 存在
- **WHEN** 客户端请求 `GET /api/v1/ingest/jobs/job_xxx`
- **THEN** 系统 SHALL 返回该任务的完整详情
- **AND** 响应 `data.job_id` SHALL 等于 `job_xxx`

#### Scenario: 查询不存在的任务详情
- **GIVEN** 任务 `job_missing` 不存在
- **WHEN** 客户端请求 `GET /api/v1/ingest/jobs/job_missing`
- **THEN** 系统 SHALL 返回 404
- **AND** 错误 `code` SHALL 为 `INGEST_JOB_NOT_FOUND`

### Requirement: 失败任务支持重试

系统 SHALL 通过 `POST /api/v1/ingest/jobs/{job_id}/retry` 对失败的入库任务创建新的重试任务，复用原任务的文档、入库模式和必要选项。

#### Scenario: 重试失败任务
- **GIVEN** 任务 `job_failed` 的状态为 `failed`
- **WHEN** 客户端请求 `POST /api/v1/ingest/jobs/job_failed/retry`
- **THEN** 系统 SHALL 提交新的入库任务
- **AND** 响应 SHALL 包含新的 `job_id`
- **AND** 新任务 SHALL 关联原任务的 `doc_id`

#### Scenario: 重试非失败任务
- **GIVEN** 任务 `job_running` 的状态为 `processing`
- **WHEN** 客户端请求 `POST /api/v1/ingest/jobs/job_running/retry`
- **THEN** 系统 SHALL 返回 409
- **AND** 错误 SHALL 表明只有失败任务可以重试

### Requirement: 入库任务可选支持取消

系统 SHALL 通过 `POST /api/v1/ingest/jobs/{job_id}/cancel` 取消尚未开始或支持协作式取消的入库任务。

#### Scenario: 取消等待中的任务
- **GIVEN** 任务 `job_pending` 的状态为 `pending`
- **WHEN** 客户端请求 `POST /api/v1/ingest/jobs/job_pending/cancel`
- **THEN** 系统 SHALL 将任务状态更新为 `canceled`

#### Scenario: 取消不可取消的任务
- **GIVEN** 任务 `job_done` 的状态为 `completed`
- **WHEN** 客户端请求 `POST /api/v1/ingest/jobs/job_done/cancel`
- **THEN** 系统 SHALL 返回 409
- **AND** 错误 SHALL 表明该任务当前不可取消
