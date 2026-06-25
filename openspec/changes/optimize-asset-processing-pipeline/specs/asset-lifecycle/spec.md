## ADDED Requirements

### Requirement: Asset 创建时不预设 mime_type

系统 SHALL 在解析阶段创建 Asset 时不再通过扩展名推断设置 `metadata["mime_type"]`。`mime_type` 仅在 Asset 处理器阶段由文件魔数推断（`sniff_image_mime` / `sniff_video_mime`）设置。

#### Scenario: 内嵌图片的 mime_type 仅由 processor 设置

- **GIVEN** DOCX/PDF/PPTX 解析器提取到内嵌图片
- **WHEN** 解析器创建 Asset 对象
- **THEN** Asset 的 `metadata` 中不包含 `mime_type` 键
- **AND** 后续 `_process_image_data` 通过魔数推断设置 `metadata["mime_type"]`

#### Scenario: 链接类型 Asset 的 mime_type 仅由 processor 设置

- **GIVEN** 解析器识别到 image_link / video_link
- **WHEN** 解析器创建 Asset 对象
- **THEN** Asset 的 `metadata` 中不包含 `mime_type` 键
- **AND** 下载字节后 `_process_image_data` / `_process_video_data` 通过魔数推断设置

#### Scenario: PPTX 内嵌图片使用 OOXML 内部类型

- **GIVEN** PPTX 解析器从 `image.content_type` 获取到 MIME 类型
- **WHEN** 解析器创建 Asset 对象
- **THEN** 保留 `image.content_type` 作为 `metadata["mime_type"]` 的值（来自文件内部元数据，可靠）
- **AND** 不使用扩展名推断作为 fallback

### Requirement: Asset 删除仅清除 PG 元数据

系统 SHALL 在删除 Asset 时仅移除 PostgreSQL 中的元数据记录，不物理删除 MinIO 文件。MinIO 文件通过 content_hash 内容寻址，同内容只有一个副本，由未来定时 GC 回收孤儿文件。

#### Scenario: 重入库时清理旧 Asset 不删 MinIO 文件

- **GIVEN** 文档 A 包含图片，已入库，MinIO 中存在对应文件
- **WHEN** 文档 A 重入库，`_cleanup_old_assets` 清理旧 Asset
- **THEN** 系统仅删除 PG 中旧 Asset 的元数据记录
- **AND** MinIO 文件保持不变
- **AND** 新入库流程计算同一 content_hash 后生成同一 MinIO key，文件自然复用

#### Scenario: 多个文档共享图片时删除一个文档不影响其他

- **GIVEN** 文档 A 和文档 B 的 Asset 因 content_hash 相同而共享同一 MinIO key
- **WHEN** 文档 A 重入库，清理其 Asset 元数据
- **THEN** PG 中文档 A 的 Asset 元数据被删除
- **AND** MinIO 文件未被删除（仅清 PG，不动 MinIO）
- **AND** 文档 B 的 Asset 仍正常可用

## MODIFIED Requirements

### Requirement: Asset content_hash 去重

系统 SHALL 对每个 Asset 计算 `content_hash`（sha256），入库前检查是否已存在相同 hash 的 Asset，若存在则复用而非重复存储。

#### Scenario: 相同图片去重复用

- **WHEN** 图片的 sha256 hash 与已有 `status=ready` 的 Asset 匹配
- **THEN** 系统复用已有 Asset 的 `storage_uri`、`extracted_text` 等字段，仅新增当前 Asset 引用，不上传重复文件到 MinIO

#### Scenario: 不同图片创建新 Asset

- **WHEN** 图片的 sha256 hash 匹配不到已有 Asset
- **THEN** 系统创建新 Asset 记录，上传图片到 MinIO，key 为 `{hash_hex[:2]}/{hash_hex}`

#### Scenario: 去重仅检查 ready 状态的 Asset

- **WHEN** 存在 hash 相同但 `status=failed` 的 Asset
- **THEN** 系统重新尝试处理（下载、校验、上传），不跳过该资源

### Requirement: 图片上传 MinIO 并更新 Asset 状态

系统 SHALL 将图片上传到 MinIO `kb-assets` Bucket，更新 Asset 的 `storage_uri` 和 `status`。

#### Scenario: 图片上传成功

- **WHEN** 图片校验通过且未命中去重
- **THEN** 图片字节上传到 MinIO，Asset 状态更新为 `status=ready`，`storage_uri` 更新为 `minio://kb-assets/{hash_hex[:2]}/{hash_hex}`

#### Scenario: 图片上传失败

- **WHEN** MinIO 上传出错（网络、权限、空间不足等）
- **THEN** Asset 状态更新为 `status=failed`，`error_message` 记录详细错误，继续处理后续资源
