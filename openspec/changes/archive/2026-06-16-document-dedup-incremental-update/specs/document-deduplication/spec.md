## ADDED Requirements

### Requirement: 上传阶段基于 source_hash 去重

系统 SHALL 在文件上传写入 MinIO 之前，通过 `source_hash` 查询 PostgreSQL 检查内容是否已存在。命中的文件不应写入对象存储。

#### Scenario: 上传已存在的文件
- **WHEN** 用户上传文件且计算出的 `source_hash` 在 `documents` 表中已存在匹配行（`status = 'active'`）
- **THEN** 系统返回 `200 OK`，响应体包含 `"duplicate": true` 和 `"existing_doc_id"` 指向已有文档，`"source_uri"` 返回已有文档的存储地址，`"file_name"`、`"size"`、`"title"`、`"category"` 返回本次上传的文件信息（供客户端参考），不写入 MinIO

#### Scenario: 上传新文件
- **WHEN** 用户上传文件且 `source_hash` 在 `documents` 表中不存在匹配行
- **THEN** 系统正常写入 MinIO，返回 `source_uri` 和 `duplicate: false`

#### Scenario: 上传与已失败文档相同内容的文件
- **WHEN** 用户上传文件且 `source_hash` 匹配到 `status = 'failed'` 的文档
- **THEN** 系统仍正常上传并返回 `duplicate: false`（允许重新入库失败的文档）

### Requirement: 入库阶段基于 source_hash 去重

系统 SHALL 在 `/ingest` 接收入库请求后，对每个文档按 `source_hash` 查询 PostgreSQL，阻止 `status='active'` 的重复文档进入入库管道。

#### Scenario: 入库已存在的活跃文档（新建模式）
- **WHEN** `/ingest` 请求中包含 `doc_id` 为空的文档，且其 `source_hash` 在数据库中匹配到 `status='active'` 的文档
- **THEN** 系统在响应 `warnings` 中返回该文档被跳过的原因，不创建新的入库任务

#### Scenario: 入库已失败文档的相同内容（新建模式）
- **WHEN** `/ingest` 请求中包含 `doc_id` 为空的文档，且其 `source_hash` 匹配到 `status='failed'` 或 `status='deleted'` 的文档
- **THEN** 系统允许重新入库，创建新的 Document 记录

#### Scenario: 入库指定了 doc_id 的文档可绕过 hash 去重
- **WHEN** `/ingest` 请求中包含 `doc_id` 已存在的文档（走更新路径）
- **THEN** 系统不执行 hash 去重检查，直接进入更新流程

### Requirement: 数据库 source_hash 部分唯一索引

数据库 SHALL 在 `documents` 表上为 `source_hash` 建立部分唯一索引，仅对 `status = 'active'` 的行生效，作为去重的最后防线。

#### Scenario: 并发插入相同 hash 的活跃文档被数据库拒绝
- **WHEN** 两个并发入库请求尝试插入相同 `source_hash` 且均设置 `status='active'`
- **THEN** 数据库层唯一索引阻止第二个插入，返回约束冲突错误
