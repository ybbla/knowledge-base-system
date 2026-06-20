# Doc Version History

## Purpose

提供文档版本历史查看能力，用户可以查看文档的更新历史记录。

## Requirements

### Requirement: 文档记录前一版本关联
文档 SHALL 在更新时通过 `previous_doc_id` 字段记录前一版本的 `doc_id`。

#### Scenario: 文档更新时记录前一版本
- **GIVEN** 用户更新文档 `doc_old`
- **WHEN** 系统创建新版本 `doc_new`
- **THEN** `doc_new.previous_doc_id` SHALL 设置为 `doc_old.doc_id`

#### Scenario: 新文档无前一版本
- **GIVEN** 用户创建新文档
- **WHEN** 文档被创建
- **THEN** `previous_doc_id` SHALL 为 `null`

### Requirement: 版本历史查看接口
系统 SHALL 提供接口查看文档的版本历史。

#### Scenario: 查询存在文档的版本历史
- **GIVEN** 文档 `doc_xxx` 存在
- **WHEN** 用户请求 `GET /api/v1/documents/doc_xxx/history`
- **THEN** 系统返回版本历史列表
- **AND** 列表按时间倒序排列（最新的在前）
- **AND** 每个版本包含基本信息（`doc_id`、`title`、`version`、`status`、`created_at`）

#### Scenario: 查询不存在文档的版本历史
- **GIVEN** 文档不存在
- **WHEN** 用户请求版本历史
- **THEN** 系统返回 404 错误
