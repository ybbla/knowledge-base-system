## 1. AssetType 枚举 + 关联死字段

- [x] 1.1 修改 `app/core/models.py` `AssetType`：删 `audio`/`attachment`，加 `image_link`/`video_link`/`document_link`，保留 `image`
- [x] 1.2 删除 `ElementType.embedded_document`（L58）
- [x] 1.3 删除 `ParsedElement.embedded_doc_id`（L144）
- [x] 1.4 清理 `embedded_doc_id` 引用：`app/db/repositories/elements.py`(L31/48)、`llm/semantic_extractor.py`(L212-213)、`app/api/v1/documents.py`(L116)
- [x] 1.5 更新 `parsers/utils.py` `guess_mime()`：`AssetType.video`→`video_link`，删 `audio` 分支，加 `image_link`→`"image/*"` 回退

## 2. 下载基础设施

- [x] 2.1 新建 `assets/downloader.py`：`download_to_bytes(url, timeout=30)`
- [x] 2.2 编写 `tests/test_downloader.py`

## 3. 资源处理函数重构

- [x] 3.1 重构 `assets/image_processor.py`：抽 `_process_image_data(data, asset, asset_store, minio_store)` 共享函数
- [x] 3.2 实现 `process_image_link(asset, asset_store, minio_store)`：HTTP下载 → `_process_image_data`
- [x] 3.3 重构 `process_video(asset, asset_store, minio_store)`：签名加 `minio_store`，加 HTTP下载 + MinIO上传
- [ ] 3.4 编写 `tests/test_image_processor.py`

## 4. Pipeline 适配

- [x] 4.1 更新 `_prepare_assets` 分支：`image`→`process_image`，`image_link`→`process_image_link`，`video_link`→`process_video`，`document_link`→`self._process_document_link`
- [x] 4.2 实现 `IngestionPipeline._process_document_link(asset)`：HTTP下载→MinIO kb-input→创建子Document→`document_repo.create()`→`self.ingest(child_doc, raw_content=data)`
- [x] 4.3 更新 `_attach_unreferenced_video_assets`(L206)：`AssetType.video` → `AssetType.video_link`
- [x] 4.4 从 `_run_create` 移除 RecursiveLoader 调用 + 清理 import

## 5. 移除 RecursiveLoader

- [x] 5.1 删除 `ingestion/recursive_loader.py`
- [x] 5.2 删除 `tests/test_recursive_loader.py`

## 6. 解析器适配

- [x] 6.1 适配 `parsers/markdown_parser.py`：`_classify_link_url`(L296/300/303) `video`→`video_link`/`image`→`image_link`/`attachment`→`document_link`；`_asset_from_image`(L305) `video`→`video_link`/`image`→`image_link`；`_extract_video_assets`(L336/348/351) `video`→`video_link`
- [x] 6.2 适配 `parsers/docx_parser.py`：`_classify_link_url`(L312/315/317) `video`→`video_link`/`image`→`image_link`/`attachment`→`document_link`；`_extract_videos` 中 `AssetType.video`→`video_link`(L611/621/624)；内嵌图片(L574)保持 `image`
- [x] 6.3 适配 `parsers/pptx_parser.py`：`_asset_type_for_url`(L824-835) 映射改为 `video`→`video_link`/`audio`→`video_link`/`document`→`document_link`；内嵌图片(L385)保持 `image`
- [x] 6.4 适配 `parsers/pdf_parser.py`：`_asset_type_for_url`(L1078+) 映射改为 `video`→`video_link`/`attachment`→`document_link`；内嵌图片(L731)保持 `image`
- [x] 6.5 适配 `parsers/xlsx_parser.py`：`_classify_link_asset_type`(L441/445/448) `video`→`video_link`/`image`→`image_link`/`attachment`→`document_link`；内嵌图片(L183)保持 `image`
- [x] 6.6 适配 `parsers/html_parser.py`：`AssetType.video`→`video_link`/`image`(URL)→`image_link`/`attachment`→`document_link`

## 7. 测试更新

- [x] 7.1 更新 `tests/test_models.py`：AssetType 枚举测试 + 删 `embedded_doc_id` 和 `ElementType.embedded_document` 断言
- [x] 7.2 更新 `tests/test_db_models.py`：删 `embedded_doc_id` 断言
- [x] 7.3 更新 `tests/test_parser_utils.py`：`guess_mime` 测试适配新枚举；删 `audio` 测试行；`attachment`→`document_link`
- [x] 7.4 更新解析器测试：`test_markdown_ingest.py`/`test_docx_parser.py`/`test_pptx_parser.py`/`test_pdf_parser.py`/`test_xlsx_parser.py`/`test_html_parser.py` 的 AssetType 断言
- [x] 7.5 更新 `tests/test_ingestion_html.py`/`test_ingestion_xlsx.py`：AssetType 断言 + 删 `embedded_doc_id`
- [x] 7.6 更新 `tests/test_db_repositories.py`/`test_image_processor_vision.py`/`test_asset_processing.py`/`test_semantic_extractor_asset_descriptions.py` 的 AssetType 断言
- [x] 7.7 运行全量测试：`pytest tests/ -v`
