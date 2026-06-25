## ADDED Requirements

### Requirement: Asset 的 MinIO key 按内容寻址

系统 SHALL 使用内容哈希（`content_hash` 的 hex digest 部分）构造 Asset 的 MinIO object key，格式为 `{hash_hex[:2]}/{hash_hex}`，确保相同内容的文件在 MinIO 中只存一份。

#### Scenario: 两个文档包含相同图片

- **GIVEN** 文档 A 和文档 B 包含相同内容的图片（sha256 一致）
- **WHEN** 文档 B 的 Asset 处理管线计算 content_hash 并上传 MinIO
- **THEN** 系统生成的 MinIO key 与文档 A 相同（`{hash_hex[:2]}/{hash_hex}`）
- **AND** MinIO 中该图片文件仅存一份

#### Scenario: 不同图片生成不同 key

- **GIVEN** 两张不同内容的图片
- **WHEN** 系统为每张图片生成 MinIO key
- **THEN** 两个 key 不同（hash_hex 不同）
- **AND** MinIO 中存储两份独立文件

#### Scenario: key 不含 doc_id

- **GIVEN** 任意 Asset 已计算 content_hash
- **WHEN** 系统生成 MinIO key
- **THEN** key 中不包含文档 ID
- **AND** 删除任意关联文档不影响其他文档对该 MinIO 文件的引用

#### Scenario: key 包含分片前缀

- **GIVEN** Asset 的 content_hash 为 `sha256:a1b2c3d4...`
- **WHEN** 系统生成 MinIO key
- **THEN** key 为 `a1/a1b2c3d4e5f6...`
- **AND** 分片前缀为 hex digest 的前 2 个字符（256 个分片目录）

### Requirement: 文档文件上传保持 doc_id 寻址

系统 SHALL 对文档文件本身（kb-input bucket）继续使用 `{doc_id[:2]}/{doc_id}/{file_name}` 格式的 MinIO key，不做内容寻址。

#### Scenario: 文档文件上传不改变 key 格式

- **WHEN** `_process_document_link` 将子文档文件上传到 kb-input bucket
- **THEN** key 格式保持 `{doc_id[:2]}/{doc_id}/{file_name}`
- **AND** 不使用 content_hash 寻址
