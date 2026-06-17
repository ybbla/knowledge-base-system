# System Health API

## Purpose

通过 `/api/v1/health` 提供进程存活、服务就绪和依赖状态检查能力，面向前端系统状态页、部署探针和运维监控。

> 同步自 change `implement-api-improvement-plan`，日期 2026-06-17。

## Requirements

### Requirement: 系统提供存活检查
系统 SHALL 通过 `GET /api/v1/health/live` 返回进程是否可响应。

#### Scenario: 服务进程可响应
- **WHEN** 客户端请求 `GET /api/v1/health/live`
- **THEN** 系统返回 200
- **AND** 响应 `data.status` 为 `ok`

### Requirement: 系统提供就绪检查
系统 SHALL 通过 `GET /api/v1/health/ready` 检查核心依赖是否达到可服务状态。

#### Scenario: 所有核心依赖可用
- **GIVEN** 文档仓储、知识块存储、向量索引、BM25 索引和资源存储均可用
- **WHEN** 客户端请求 `GET /api/v1/health/ready`
- **THEN** 系统返回 200
- **AND** 响应 `data.status` 为 `ok`

#### Scenario: 核心依赖不可用
- **GIVEN** 向量索引不可用
- **WHEN** 客户端请求 `GET /api/v1/health/ready`
- **THEN** 系统返回 503 或返回 `data.status=degraded`
- **AND** 响应 SHALL 标明失败依赖

### Requirement: 系统提供依赖状态详情
系统 SHALL 通过 `GET /api/v1/health/dependencies` 返回后端、仓储、索引、LLM、Embedding 和资源存储的状态详情。

#### Scenario: 查看依赖状态详情
- **WHEN** 客户端请求 `GET /api/v1/health/dependencies`
- **THEN** 响应 SHALL 包含 `backend`
- **AND** 响应 SHALL 包含 `document_repo`、`element_repo`、`chunk_store`、`vector_index`、`bm25_index`、`embedding`、`llm` 和 `asset_store` 的状态

#### Scenario: 依赖检查不得暴露敏感信息
- **GIVEN** 某个依赖检查失败并产生底层异常
- **WHEN** 系统返回依赖状态详情
- **THEN** 响应 SHALL 返回错误摘要
- **AND** 响应 MUST NOT 暴露密钥、连接密码或完整堆栈
