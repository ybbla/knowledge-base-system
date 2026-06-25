## Context

当前 Asset 处理链路横跨解析（parser）、资源处理（asset_processor）、入库管道（pipeline）、语义抽取（semantic_extractor）四层，涉及 8 个解析器和 3 个存储后端（PG、MinIO、Milvus）。存在以下技术债务：

- MinIO key 格式为 `{doc_id[:2]}/{doc_id}/{asset_id}/{file_name}`，绑定在第一个上传文档的 ID 上。`find_ready_duplicate` 虽实现了 storage_uri 的跨文档复用，但删除该文档时 `MinioAssetStore.delete()` 直接物理删除 MinIO 文件，导致其他复用此文件的文档悬空引用。
- `mime_type` 在两个阶段被分别设置：解析阶段用 `guess_mime(url)`（扩展名推断，不可靠），processor 阶段用 `sniff_*_mime(data)`（魔数推断，可靠）覆盖。双重写入且前者冗余。
- `_elements_to_json` 在 LLM prompt 中输出 `url` 字段，但 LLM 无法访问 `minio://` 内部地址，对语义抽取无价值。
- `_run_create` 中 Asset 先逐条 commit，Element 后批量 commit，不在同一事务。Element 写入失败时 Asset 已成孤儿。
- `create_batch` 逐条 `merge()`（N 次 SELECT + N 次 INSERT/UPDATE），入库场景元素全新建，merge 的 SELECT 是浪费。
- `_prepare_assets` 逐条串行处理 image/video 类 Asset，每个带 LLM 视觉调用（2-5 秒），10 张图片阻塞 20-50 秒。

## Goals / Non-Goals

**Goals:**
- MinIO 中的 Asset 文件按内容寻址，同内容跨文档自动复用且互不影响
- MinIO 文件只增不删，删除 Asset 仅清 PG 元数据
- `mime_type` 仅在 processor 阶段由魔数推断确定，解析阶段不再写入
- LLM prompt 中移除无用的 `url`，减少 token 消耗
- Element 先于 Asset 持久化，核心数据优先保证
- `create_batch` 使用真正的批量插入
- image/video 类 Asset 并发处理，缩短入库延迟

**Non-Goals:**
- 不引入 MinIO 文件定时 GC 机制（本次仅解决"不误删"，GC 在后续实现）
- 不改变 Asset 与 Element 的跨 repository 事务模型
- 不修改 `document_link` 的处理流程
- 不改变 `AssetData.placeholder` 格式（已在另一个 change 中处理）
- 不引入消息队列或异步任务系统

## Decisions

### D1: MinIO key 使用 content_hash 内容寻址

**选择**：`make_asset_key(content_hash)` → `{hash_hex[:2]}/{hash_hex}`

**理由**：
- 同内容自动同 key，MinIO 层天然去重，无需依赖 PG 查询
- key 不含 doc_id，文档删除不影响其他文档的引用
- 256 个分片目录（hex 前两位），分布均匀

**保留 `make_minio_key`** 用于文档文件上传（`_process_document_link` 写 kb-input bucket，文档文件不需要内容寻址）。

### D2: MinIO 文件只增不删

**选择**：`MinioAssetStore.delete()` 和 `_cleanup_old_assets` 仅删除 PG 元数据，不调 `remove_object`。

**理由**：
- 内容寻址下同 content_hash → 同 key，不存在"删了 A 的 MinIO 文件导致 B 悬空"的问题——因为 A 删时只是清了自己的 PG 记录，B 的 PG 记录仍指向同一 key
- 删 MinIO 文件本身是多余的：key 由 content_hash 决定，下一轮入同一图片会自动复用同一 key
- 即使所有引用都删了、文件变成孤儿，也只是占点空间，不影响正确性

**备选方案**：引用计数 → 引入查询复杂度，但内容寻址下根本不需要——同 key 共享是天然的，比引用计数更根本地解决了问题。

### D3: mime_type 仅由 processor 设置

在 `_process_image_data` / `_process_video_data` 中通过魔数推断后写入 `asset.metadata["mime_type"]`，作为唯一权威写入点。所有解析器删除 `guess_mime()` 调用。

唯一例外：`pptx_parser` 内嵌图片的 `image.content_type` 来自 OOXML 内部元数据，可靠，保留。

### D4: _elements_to_json 去掉 url

删除 `item["asset_data"][*]["url"]`，只保留 `placeholder`、`asset_id`、`type`。

LLM 无法访问 `minio://` 地址，url 对语义抽取无实际价值。检索结果中的资源 URL 由 `RetrievalPipeline` 从 Asset 表直接查。

### D5: Element 先于 Asset 写入

`_run_create` 中 `create_batch(elements)` 移至 `_prepare_assets(assets)` 之前。Element 是核心数据，优先持久化；Asset 是附属数据，写入失败可容忍。

### D6: create_batch 用批量插入

`session.bulk_save_objects()` 替代 `session.merge()`。前提：pipeline 的 `_cleanup_previous_artifacts` 已调用 `delete_by_doc_id` 清空旧数据。

### D7: Asset 处理用线程池并发

`ThreadPoolExecutor(max_workers=4)` 并发处理 image/video 类 Asset。`PgAssetStore.put()` 每次创建独立 session，天然线程安全。`minio-py` 客户端线程安全。document_link 保持串行（内部创建子文档 + 异步入库）。

## Risks / Trade-offs

- **[MinIO key 格式变更]** → 提供升级说明：存量文件保留在旧路径，新入库文件用新路径。旧文件在重入库时自然替换为新格式。
- **[MinIO 文件永不删除]** → 磁盘占用逐步增长。后续引入定时 GC（扫描 PG 中所有 storage_uri，删除不在其中的 MinIO key）。
- **[并发处理 LLM rate limit]** → `max_workers=4` 保守值，单个 Asset 失败不阻塞其他。
- **[create_batch 不再 merge]** → 如果未来有场景不经 `delete_by_doc_id` 直接调 `create_batch`，会因主键冲突报错。当前所有调用路径都先 delete 再 create，安全。
- **[Element 先写，Asset 后写]** → 入库失败重试时 element 已存在（再次入库会先清理），不影响正确性。
