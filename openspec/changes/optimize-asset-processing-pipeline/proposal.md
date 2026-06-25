## Why

当前 Asset 处理链路存在六个问题：MinIO key 绑定在文档 ID 上导致跨文档复用后删除文档会断开其他文档的引用；`mime_type` 在解析阶段和 processor 阶段被重复设置，前者不可靠；LLM 抽取时将不可访问的 `url` 写进 prompt 浪费 token；Element 写入在 Asset 写入之后，Element 失败产生孤儿 Asset；`create_batch` 逐条 merge 而非批量插入；Asset 的 image/video 视觉处理串行阻塞主链路。需要系统性地修复这些问题。

## What Changes

- **MinIO key 改为 content_hash 内容寻址**：Asset 文件按 `{hash_hex[:2]}/{hash_hex}` 存储，同内容文件在 MinIO 中仅存一份，不受文档删除影响。**BREAKING**：存量 MinIO 文件的 key 格式变更，需迁移或接受新旧并存。
- **MinIO 文件只增不删**：`MinioAssetStore.delete()` 和 `_cleanup_old_assets` 仅删除 PG 元数据，不再物理删除 MinIO 文件。content_hash 寻址下同内容自动同 key，不存在"删错文件"问题。孤儿文件由未来定时 GC 回收。
- **消除 `mime_type` 双重设置**：各解析器不再在创建 Asset 时调用 `guess_mime()` 设置 `metadata["mime_type"]`，统一由 processor 的 `sniff_*_mime()` 魔数推断作为唯一写入点。
- **`_elements_to_json` 去掉 `url` 字段**：LLM prompt 中的 asset_data 不再包含 `url`，减少无效 token 消耗。检索时 URL 从 Asset 表直接查。
- **Element 先于 Asset 写入 PG**：调整 `_run_create` 顺序，element（核心数据）先持久化，asset（附属数据）后持久化。
- **`create_batch` 性能优化**：改用 `bulk_save_objects` 替代逐条 `merge`。
- **Asset 处理并行化**：image/video 类 Asset 用线程池并发处理，document_link 保持串行。

## Capabilities

### New Capabilities

- `asset-content-addressed-storage`: Asset 的 MinIO key 按 content_hash 内容寻址，同内容跨文档自动复用一份文件；MinIO 文件只增不删

### Modified Capabilities

- `asset-lifecycle`: 移除解析阶段的 `guess_mime()` 调用；MinIO key 格式变更；删除 Asset 仅清 PG 元数据
- `minio-storage`: 新增 `make_asset_key(content_hash)` 内容寻址函数；`delete()` 不删 MinIO 文件；`put()` 的 Content-Type 从 metadata 读取
- `document-ingestion`: `_run_create` 中 Element 先于 Asset 写入；`_prepare_assets` 支持并发处理；`create_batch` 性能优化
- `semantic-extraction`: `_elements_to_json` 的输出中 asset_data 移除 `url` 字段
- `image-vision-understanding`: mime_type 的来源从"解析阶段设置后被覆盖"变为"仅 processor 阶段设置"
- `video-vision-understanding`: 同上
- `docx-parsing`: 移除 Asset 创建时的 `guess_mime()` 调用
- `pdf-parsing`: 移除 Asset 创建时的 `guess_mime()` 和 `_guess_image_mime()` 调用
- `pptx-parsing`: 移除链接 Asset 创建时的 `guess_mime()` 调用，保留内嵌图片的 `image.content_type`
- `xlsx-parsing`: 移除 Asset 创建时的 `guess_mime()` 调用
- `html-parsing`: 移除 Asset 创建时的 `_guess_mime()` 调用
- `markdown-parsing`: 移除 Asset 创建时的 `guess_mime()` 调用

## Impact

- **Affected code**: 8 个解析器、`asset_processor.py`、`minio_store.py`、`pipeline.py`、`elements.py`、`semantic_extractor.py`、`utils.py`
- **Breaking change**: MinIO key 格式从 `{doc_id[:2]}/{doc_id}/{asset_id}/{file_name}` 变为 `{hash_hex[:2]}/{hash_hex}`，存量数据需迁移脚本或直接在重入库时自然替换
- **Dependencies**: 无外部依赖变更
- **Rollback**: MinIO key 变更不可回滚（已写入的新格式文件需脚本迁移回去）；其余改动均可直接 revert 代码
