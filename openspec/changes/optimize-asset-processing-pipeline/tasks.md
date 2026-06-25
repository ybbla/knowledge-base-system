## 1. MinIO content_hash 内容寻址

- [x] 1.1 新增 `make_asset_key(content_hash)` 函数到 [minio_store.py](knowledge_base_system/assets/minio_store.py)，格式 `{hash_hex[:2]}/{hash_hex}`
- [x] 1.2 [asset_processor.py:200-201](knowledge_base_system/assets/asset_processor.py#L200) `_process_image_data` 改用 `make_asset_key(asset.content_hash)` 替代 `make_minio_key(doc_id, file_name, asset_id)`
- [x] 1.3 [asset_processor.py:278](knowledge_base_system/assets/asset_processor.py#L278) `_process_video_data` 同上
- [x] 1.4 [minio_store.py:112-114](knowledge_base_system/assets/minio_store.py#L112) `put()` 中先算 content_hash 再调用 `make_asset_key`；Content-Type 从 `asset.metadata.get("mime_type")` 读取
- [x] 1.5 [minio_store.py:131-140](knowledge_base_system/assets/minio_store.py#L131) `delete()` 删除 `remove_object` 调用，仅保留 `_metadata_store.delete(asset_id)`；更新方法注释

## 2. 消除 mime_type 双重设置

- [x] 2.1 `parsers/docx_parser.py`: 删除 4 处 `"mime_type": guess_mime(...)`（行 227、265、478、663），删除 `guess_mime` import
- [x] 2.2 `parsers/markdown_parser.py`: 删除 2 处 `"mime_type": guess_mime(...)`（行 97、143），删除 `guess_mime` import
- [x] 2.3 `parsers/html_parser.py`: 删除行 545 的 `_guess_mime` 调用，删除 `_guess_mime()` 方法
- [x] 2.4 `parsers/pdf_parser.py`: 删除行 893/907 嵌入图片的 mime_type、行 1050 链接的 mime_type；删除 `_guess_image_mime` / `_guess_mime` 方法
- [x] 2.5 `parsers/pptx_parser.py`: 行 491 保留 `image.content_type`，删除 `guess_mime` fallback；行 700 删除链接的 `guess_mime`；删除 `guess_mime` import
- [x] 2.6 `parsers/xlsx_parser.py`: 删除行 176、387 的 `guess_mime` 调用，删除 `guess_mime` import
- [x] 2.7 `parsers/utils.py`: `guess_mime()` 函数加注释标注"不建议在 Asset 创建时调用"

## 3. _elements_to_json 去掉 url 字段

- [x] 3.1 修改 [semantic_extractor.py:429](knowledge_base_system/llm/semantic_extractor.py#L429)，asset_data 输出中删除 `url` 字段
- [x] 3.2 检查 `test_semantic_extractor_full_doc.py` 中相关的 JSON 期望值（无期望 url 字段的断言，无需修改）

## 4. Element/Asset PG 写入顺序 + 并行化

- [x] 4.1 修改 [pipeline.py:200-206](knowledge_base_system/ingestion/pipeline.py#L200-L206) `_run_create`，`create_batch(elements)` 移至 `_prepare_assets(assets)` 之前
- [x] 4.2 重构 [pipeline.py:219-242](knowledge_base_system/ingestion/pipeline.py#L219-L242) `_prepare_assets`，按类型分组，`ThreadPoolExecutor(max_workers=4)` 并发处理 image/video/image_link/video_link，document_link 保持串行
- [x] 4.3 新增模块级 `_dispatch_asset(asset, asset_store, minio_store)` 纯函数，供线程池调用

## 5. create_batch 性能优化

- [x] 5.1 修改 [elements.py:55-61](knowledge_base_system/app/db/repositories/elements.py#L55-L61) `create_batch`，用 `session.bulk_save_objects()` 替代逐条 `session.merge()`

## 6. 测试更新

- [x] 6.1 运行 `pytest tests/ -v`，确认 mime_type / url 字段变更无新增失败（semantic_extractor 测试全部通过；docx/xlsx/pptx 失败均为已有问题）
- [x] 6.2 运行 `pytest tests/ -v`，确认 Element/Asset 写入顺序和 create_batch 批量插入无回归

## 7. 集成验证

- [ ] 7.1 清空数据库，上传含图片的文档，验证 MinIO 文件按 content_hash 寻址
- [ ] 7.2 上传另一文档包含相同图片（可改名），验证 MinIO 仅存一份、两个文档的 Asset 引用同一 storage_uri
- [ ] 7.3 删除/重入库文档 A，验证文档 B 的 Asset 仍可正常访问（MinIO 文件未被误删）
- [ ] 7.4 上传含多张图片的文档，验证并行处理后所有图片的 extracted_text 均正确
