# File Upload

## Purpose

提供本地文件上传接口，接收 multipart/form-data 文件，写入本地存储，返回 `source_uri` 供后续 `/ingest` 使用。

> 新建自 change `align-data-model-and-api-with-updated-design`，日期 2026-06-10。

## Requirements

### Requirement: 文件上传并写入本地存储

系统 SHALL 提供 `/upload` 端点，接收 multipart/form-data 文件并写入本地存储目录。

#### Scenario: 上传 DOCX 文件

- **WHEN** 客户端通过 `POST /upload` 以 multipart/form-data 提交 `file=manual.docx`、`title=产品说明书`、`category=产品使用`
- **THEN** 文件写入 `data/uploads/` 目录，返回 `source_uri`（`file://data/uploads/{uuid}.docx`）、`source_hash`（sha256）、`file_name` 和 `size`

#### Scenario: 上传时未指定 title

- **WHEN** 客户端仅提交 `file` 未提供 `title`
- **THEN** 返回的响应中 title 为文件名（不含扩展名）

#### Scenario: 上传时未指定 category

- **WHEN** 客户端仅提交 `file` 未提供 `category`
- **THEN** category 使用默认值 `"通用"`

#### Scenario: 文件存储目录自动创建

- **WHEN** `data/uploads/` 目录不存在
- **THEN** 系统自动创建目录，文件写入成功
