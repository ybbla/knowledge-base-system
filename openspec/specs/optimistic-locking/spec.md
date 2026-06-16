# Optimistic Locking

## Purpose

文档级别的乐观锁——更新时校验 `version` 字段，防止并发更新覆盖。同时将 `DocumentRepository.create()` 从静默 upsert 改为显式插入检查。

> 新建自 change `document-dedup-incremental-update`，日期 2026-06-15。

## Requirements

### Requirement: 文档更新时乐观锁检查

系统 SHALL 在执行文档更新操作时使用乐观锁：`UPDATE` 语句的 `WHERE` 条件中包含 `version = :expected`，只有版本号匹配时才执行更新并递增 `version`。

#### Scenario: 乐观锁成功
- **WHEN** 调用 `DocumentRepository.update(doc)` 且数据库中该文档的 `version` 与 `doc.version` 一致
- **THEN** 更新成功，`version` 递增 1

#### Scenario: 乐观锁冲突
- **WHEN** 调用 `DocumentRepository.update(doc)` 且数据库中该文档的 `version` 已被其他并发操作修改（不等于 `doc.version`）
- **THEN** 更新影响行数为 0，系统抛出 `VersionConflictError`

### Requirement: VersionConflictError 异常类型

系统 SHALL 定义 `VersionConflictError` 异常类型，归属于 `KnowledgeBaseError` 体系。当乐观锁冲突时抛出此异常。

#### Scenario: API 层捕获冲突异常
- **WHEN** 入库管道捕获到 `VersionConflictError`
- **THEN** 系统记录 WARNING 日志，将 job 状态标记为 `failed`，错误信息包含 "版本冲突" 描述

### Requirement: DocumentRepository.create 先检查后插入

`DocumentRepository.create()` SHALL 改为先执行 `SELECT` 检查 `doc_id` 是否已存在，存在则抛出 `DuplicateDocumentError`，不存在才执行 `INSERT`。不再使用 `session.merge()` 的静默 upsert 行为。

#### Scenario: 创建新文档成功
- **WHEN** `doc_id` 在数据库中不存在
- **THEN** 执行 `INSERT` 写入新文档记录

#### Scenario: 创建重复文档失败
- **WHEN** `doc_id` 在数据库中已存在
- **THEN** 抛出 `DuplicateDocumentError`

### Requirement: DuplicateDocumentError 异常类型

系统 SHALL 定义 `DuplicateDocumentError` 异常类型，归属于 `KnowledgeBaseError` 体系。当尝试创建已存在的文档时抛出此异常。

#### Scenario: 上传层捕获重复异常
- **WHEN** 上传 API 检测到重复文档
- **THEN** 返回 `200 OK` 而非 `4xx`，响应体包含 `duplicate: true` 和已有文档信息（上传去重视为正常流程而非错误）
