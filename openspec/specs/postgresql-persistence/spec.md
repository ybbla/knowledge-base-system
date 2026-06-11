# PostgreSQL Persistence

## Purpose

将 Document / ParsedElement / Asset / KnowledgeChunk 四个核心实体的元数据持久化到 PostgreSQL，使服务重启后数据不丢失。向量索引和 BM25 索引在阶段 2 仍保持内存实现，阶段 3 迁移至 Milvus。

## Requirements

### Requirement: PostgreSQL 连接与会话管理

系统 SHALL 支持通过环境变量配置 PostgreSQL 连接，并提供 FastAPI 依赖注入的数据库会话。

#### Scenario: 通过环境变量配置连接

- **WHEN** 设置 `BACKEND=postgres` 和 `DATABASE_URL=postgresql://kbuser:kbpass@localhost:5432/knowledge_base`
- **THEN** 系统使用该连接串创建 SQLAlchemy engine，连接池大小为 5

#### Scenario: 默认使用内存模式

- **WHEN** 未设置 `BACKEND` 或其值为 `memory`
- **THEN** 系统使用内存实现，不尝试连接 PostgreSQL

#### Scenario: PostgreSQL 不可达时启动报错

- **WHEN** `BACKEND=postgres` 但 PostgreSQL 未运行
- **THEN** 应用启动时抛出明确错误信息，包含连接串和失败原因

#### Scenario: 每个请求获取独立会话

- **WHEN** 后端为 postgres 模式，处理 HTTP 请求
- **THEN** 为该请求创建独立数据库会话，请求结束时自动关闭并归还连接池

### Requirement: 核心实体持久化

系统 SHALL 将 Document、ParsedElement、Asset 和 KnowledgeChunk 持久化到 PostgreSQL。

#### Scenario: Document 持久化与查询

- **WHEN** 创建 Document 记录
- **THEN** 记录写入 `documents` 表，可通过 `doc_id` 查询
- **AND** 支持按 `category`、`status`、`ingest_job_id` 过滤查询

#### Scenario: ParsedElement 持久化

- **WHEN** 文档解析生成 ParsedElement 列表
- **THEN** 所有元素写入 `parsed_elements` 表
- **AND** 可通过 `doc_id` 和 `sequence_order` 排序查询

#### Scenario: Asset 持久化

- **WHEN** 解析过程创建 Asset 记录
- **THEN** Asset 写入 `assets` 表，可通过 `asset_id` 或 `doc_id` 查询

#### Scenario: KnowledgeChunk 持久化

- **WHEN** LLM 语义抽取生成 KnowledgeChunk 列表
- **THEN** 所有 chunk 写入 `knowledge_chunks` 表
- **AND** 写入 chunk_store（PG 模式下为 PgChunkStore），可通过 `chunk_id` 批量查询
- **AND** `asset_refs` 和 `source_refs` 以 JSONB 格式存储

#### Scenario: 服务重启后数据保留

- **WHEN** 应用重启
- **THEN** 所有之前持久化的 Document / ParsedElement / Asset / KnowledgeChunk 仍可通过 API 查询
- **AND** 内存索引为空（需新入库重建索引）

### Requirement: PG 模式下组件实现与内存模式可切换

系统 SHALL 在 PG 模式下提供 `AssetStore` 和 chunk_store 的 PostgreSQL 实现，通过 `deps.py` 自动选择。

#### Scenario: PG 模式下使用 PgAssetStore

- **WHEN** `BACKEND=postgres`
- **THEN** `asset_store` 为 PgAssetStore 实例，`put()` 写入 PostgreSQL，`get()` 从 PostgreSQL 查询

#### Scenario: PG 模式下使用 PgChunkStore

- **WHEN** `BACKEND=postgres`
- **THEN** `chunk_store` 为 PgChunkStore 实例，支持 `put()`、`get()` 和 `get_batch()` 操作

#### Scenario: 内存模式不受影响

- **WHEN** `BACKEND=memory`（或不设置）
- **THEN** 所有行为与阶段 1 完全一致，不访问 PostgreSQL
