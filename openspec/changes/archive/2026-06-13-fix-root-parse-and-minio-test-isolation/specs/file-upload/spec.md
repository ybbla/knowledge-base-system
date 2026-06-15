## MODIFIED Requirements

### Requirement: 文件上传并写入本地存储

系统 SHALL 提供 `/upload` 端点，接收 multipart/form-data 文件并写入存储后端。当 MinIO 可用（`MINIO_ENABLED=true`）时写入 MinIO `kb-input` Bucket；当 MinIO 未启用或不可用时写入本地磁盘 `data/uploads/` 目录。上传行为 MUST 由显式配置决定，测试和验证场景不得依赖开发者本机 `.env` 的隐式状态。

#### Scenario: 上传 DOCX 文件到 MinIO

- **GIVEN** MinIO 已启用且可用
- **WHEN** 客户端通过 `POST /upload` 以 multipart/form-data 提交 `file=manual.docx`、`title=产品说明书`、`category=产品使用`
- **THEN** 文件写入 MinIO `kb-input/{doc_id[:2]}/{doc_id}/manual.docx`
- **AND** 响应返回 `source_uri`（`minio://kb-input/{doc_id[:2]}/{doc_id}/manual.docx`）、`source_hash`（sha256）、`file_name` 和 `size`

#### Scenario: 上传文件到本地磁盘（MinIO 未启用）

- **GIVEN** MinIO 未启用
- **WHEN** 客户端通过 `POST /upload` 提交文件
- **THEN** 文件写入 `data/uploads/` 目录
- **AND** 响应返回 `source_uri`（`file://data/uploads/{uuid}.{ext}`）、`source_hash`、`file_name` 和 `size`

#### Scenario: 上传文件到本地磁盘（MinIO 不可用时回退）

- **GIVEN** MinIO 已启用但上传初始化或写入失败
- **WHEN** 客户端通过 `POST /upload` 提交文件
- **THEN** 系统回退写入 `data/uploads/` 目录
- **AND** 响应返回 `source_uri`（`file://data/uploads/{uuid}.{ext}`）、`source_hash`、`file_name` 和 `size`

#### Scenario: 上传时未指定 title

- **GIVEN** MinIO 配置状态已由测试或运行环境显式确定
- **WHEN** 客户端仅提交 `file` 未提供 `title`
- **THEN** 返回的响应中 title 为文件名（不含扩展名）

#### Scenario: 上传时未指定 category

- **GIVEN** MinIO 配置状态已由测试或运行环境显式确定
- **WHEN** 客户端仅提交 `file` 未提供 `category`
- **THEN** category 使用默认值 `"通用"`

#### Scenario: 文件存储目录自动创建

- **GIVEN** MinIO 未启用且 `data/uploads/` 目录不存在
- **WHEN** 客户端通过 `POST /upload` 提交文件
- **THEN** 系统自动创建目录，文件写入成功

#### Scenario: MinIO 存储路径自动分片

- **GIVEN** MinIO 已启用且可用
- **WHEN** 文件上传到 MinIO 时
- **THEN** 存储路径按 `{doc_id[:2]}/{doc_id}/{file_name}` 分片，确保单目录文件数可控
