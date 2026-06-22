## 1. AssetType 枚举 + 关联死字段清理

- [ ] 1.1 修改 `app/core/models.py` `AssetType`：删除 `audio`、`attachment`，新增 `image_link`、`video_link`、`document_link`，保留 `image`
- [ ] 1.2 删除 `ElementType.embedded_document` 枚举值
- [ ] 1.3 删除 `ParsedElement.embedded_doc_id` 字段 + 清理所有引用点：`app/db/models.py`（列保留）、`app/db/repositories/elements.py`（去掉映射）、`app/api/v1/documents.py`（去掉返回字段）、`llm/semantic_extractor.py`（去掉 `embedded_doc_id` 分支）
- [ ] 1.4 更新 `parsers/utils.py` 中 `guess_mime()`：`AssetType.video`→`video_link`，删除 `audio` 分支，新增 `image_link`→`"image/*"` 回退

## 2. 下载基础设施

- [ ] 2.1 新建 `assets/downloader.py`：实现 `download_to_bytes(url, timeout=30)` 工具函数
- [ ] 2.2 编写 `tests/test_downloader.py`

## 3. 资源处理函数重构

- [ ] 3.1 重构 `assets/image_processor.py`：从 `process_image` 抽 `_process_image_data(data, asset, asset_store, minio_store)` 共享函数
- [ ] 3.2 实现 `process_image_link(asset, asset_store, minio_store)`：HTTP下载 → `_process_image_data`
- [ ] 3.3 重构 `process_video(asset, asset_store, minio_store)`：签名加 `minio_store`，补充 HTTP 下载 + MinIO 上传
- [ ] 3.4 编写 `tests/test_image_processor.py`

## 4. Pipeline 适配

- [ ] 4.1 更新 `_prepare_assets` 分支：`image`→`process_image`，`image_link`→`process_image_link`，`video_link`→`process_video`，`document_link`→`self._process_document_link`
- [ ] 4.2 实现 `IngestionPipeline._process_document_link(asset)`：HTTP下载→上传MinIO kb-input→创建子Document→`document_repo.create()`→`self.ingest(child_doc, raw_content=data)`
- [ ] 4.3 更新 `_attach_unreferenced_video_assets`：`AssetType.video` → `AssetType.video_link`
- [ ] 4.4 从 `_run_create` 移除 RecursiveLoader 调用

## 5. 移除 RecursiveLoader

- [ ] 5.1 删除 `ingestion/recursive_loader.py`
- [ ] 5.2 删除 `tests/test_recursive_loader.py`
- [ ] 5.3 清理 `pipeline.py` 中 RecursiveLoader 相关 import

## 6. 解析器适配

- [ ] 6.1 适配 `parsers/markdown_parser.py`：`_asset_from_image` 中 `AssetType.image`→`image_link`（Markdown 图片均为外部 URL）；`_classify_link_url` 返回值适配新枚举；`_extract_video_assets` 中 `AssetType.video`→`video_link`；`[[link]]` 不再设 `embedded_doc_id`，改为 `document_link`
- [ ] 6.2 适配 `parsers/docx_parser.py`：`_classify_link_url` 中 `AssetType.video`→`video_link`、`AssetType.image`→`image_link`（链接URL非内嵌字节）、`AssetType.attachment`→`document_link`
- [ ] 6.3 适配 `parsers/pptx_parser.py`：`AssetType.video`→`video_link`、`AssetType.audio`→`video_link`、`AssetType.attachment`→`document_link`；`_guess_mime` 适配
- [ ] 6.4 适配 `parsers/pdf_parser.py`：`AssetType.video`→`video_link`、`AssetType.attachment`→`document_link`；`_asset_type_for_url` 适配
- [ ] 6.5 适配 `parsers/xlsx_parser.py`：`AssetType.video`→`video_link`、`AssetType.attachment`→`document_link`；`_asset_type_for_url` 适配

## 7. 测试更新

- [ ] 7.1 更新 `tests/test_models.py`：AssetType 枚举测试 + 删除 `embedded_doc_id` 和 `ElementType.embedded_document` 相关断言
- [ ] 7.2 更新 `tests/test_db_models.py`：删除 `embedded_doc_id` 和 `ElementType.embedded_document` 相关断言
- [ ] 7.3 更新 `tests/test_markdown_ingest.py`：`[[link]]` → `document_link` 断言
- [ ] 7.4 更新 `tests/test_parser_registry.py`：如有涉及 AssetType 的测试
- [ ] 7.5 更新 `tests/test_parser_utils.py`：`guess_mime` 测试适配新枚举
- [ ] 7.6 更新 `tests/test_ingestion_xlsx.py`：删除 `embedded_doc_id` 相关断言
- [ ] 7.7 运行全量测试：`pytest tests/ -v`
