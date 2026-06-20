# Doc Update Flow

## Purpose

提供文档更新流程，包括上传时自动检测同名文件、用户确认更新、软删除旧版本并创建新版本的完整交互体验。

## Requirements

### Requirement: 上传时自动检测同名文件
系统 SHALL 在用户上传文件时，在检测到 `source_hash` 不重复的前提下，检测是否存在同名文件，并在返回结果中标注。

#### Scenario: 未检测到同名文件时直接创建
- **GIVEN** 上传的文件内容不重复
- **GIVEN** 不存在同名的活跃文档
- **WHEN** 用户上传文件
- **THEN** 系统直接创建新文档并开始入库

#### Scenario: 检测到单个同名文件时提示
- **GIVEN** 上传的文件内容不重复
- **GIVEN** 存在一个同名的活跃文档
- **WHEN** 用户上传文件
- **THEN** 系统返回 `suggested_replace=true`
- **AND** 返回包含 `suggested_doc_id` 和 `suggested_doc_title`
- **AND** 不创建文档也不保存文件

#### Scenario: 检测到多个同名文件时不提示
- **GIVEN** 上传的文件内容不重复
- **GIVEN** 存在多个同名的活跃文档
- **WHEN** 用户上传文件
- **THEN** 系统直接创建新文档并开始入库

### Requirement: 支持确认更新同名文件
用户 SHALL 可以在收到同名提示后，通过再次上传并指定 `replace_doc_id` 和 `confirm_replace=true` 来确认更新。

#### Scenario: 用户确认更新
- **GIVEN** 系统已返回 `suggested_replace=true`
- **WHEN** 用户再次上传文件，带上 `replace_doc_id` 和 `confirm_replace=true`
- **THEN** 系统软删除旧文档（`status=deleted`）
- **AND** 系统软删除旧文档的所有知识块（`status=deleted`）
- **AND** 系统从索引中移除旧知识块
- **AND** 系统创建新文档，`previous_doc_id` 指向旧文档
- **AND** 系统保存文件并开始入库

#### Scenario: 更新不存在的文档
- **GIVEN** 用户指定 `replace_doc_id` 指向不存在的文档
- **WHEN** 用户上传文件并确认更新
- **THEN** 系统返回 404 错误

#### Scenario: 取消更新
- **GIVEN** 系统已返回 `suggested_replace=true`
- **WHEN** 用户取消更新操作
- **THEN** 不执行任何操作

### Requirement: 文档列表提供更新按钮
文档管理列表 SHALL 为每个活跃文档提供"更新"按钮，点击后直接进入更新流程。

#### Scenario: 通过更新按钮更新文档
- **GIVEN** 用户在文档列表中看到活跃文档
- **WHEN** 用户点击该文档的"更新"按钮
- **THEN** 弹出文件选择窗口
- **WHEN** 用户选择文件并上传
- **THEN** 前端自动带上 `replace_doc_id` 和 `confirm_replace=true`
- **THEN** 系统执行更新流程
