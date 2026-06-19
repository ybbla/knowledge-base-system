## 1. 空 source_hash 误判修复

- [x] 1.1 修复 `app/api/ingest.py:47` — 在 `existing.source_hash == item.source_hash` 前增加 `item.source_hash and` 判空条件，空 hash 不跳过入库
- [x] 1.2 添加注释说明"空 hash 表示未计算，不能作为 no_change 依据"
- [x] 1.3 同步检查 `app/api/documents.py` 遗留端点是否有相同逻辑，如有则同步修复
- [x] 1.4 编写单元测试 `test_ingest_empty_hash_not_skipped` — 验证双方 source_hash 为空时正常进入入库流程而非被跳过

## 2. 多 categories 检索修复

- [x] 2.1 重构 `app/api/v1/search.py:_execute_search` — 当 `filters.categories` 有多个值时，对每个 category 分别调用 `retrieval_pipeline.search()`，合并结果并按 chunk_id 去重（保留最高分）
- [x] 2.2 单 category 或无 category 时保持原有逻辑不变（仅传该 category 或 None）
- [x] 2.3 更新 `_filter_and_enrich_result` 中多 category 过滤逻辑 — 合并检索后不再需要在该函数中按 category 二次过滤（已由分category检索保证）
- [x] 2.4 编写测试 `test_multi_category_search` — 验证多 category 检索结果包含所有指定分类的 chunk
- [x] 2.5 编写测试 `test_single_category_search_unchanged` — 验证单 category 检索行为不变

## 3. 上传孤儿文件修复

- [x] 3.1 调整 `app/api/v1/documents.py:upload_document` 流程 — 先调用 `document_repo.create(doc)` 预占位，再调用 `save_upload_file` 写文件
- [x] 3.2 若 `save_upload_file` 失败，删除已创建的 Document 记录回滚（调用 `document_repo.soft_delete(doc.doc_id)` 或标记为 failed）
- [x] 3.3 若 `document_repo.create()` 抛出 `DuplicateDocumentError`，确保不执行 `save_upload_file`，直接返回错误
- [x] 3.4 编写测试 `test_upload_duplicate_no_orphan_file` — 模拟并发重复上传，验证不产生孤儿文件

## 4. 枚举无效值 500 修复

- [x] 4.1 修复 `app/api/v1/documents.py:update_document` — 用 try-except 包裹 `DocStatus(status)`，捕获 ValueError 返回 422 错误响应（code=`VALIDATION_ERROR`）
- [x] 4.2 修复 `app/api/v1/chunks.py:update_chunk` — 用 try-except 包裹 `ChunkStatus(chunk_status)`，捕获 ValueError 返回 422 错误响应
- [x] 4.3 修复 `app/api/v1/chunks.py:batch_chunk_operation` — 同样包裹 `ChunkStatus(new_status)`，避免批量操作中无效状态导致 500
- [x] 4.4 编写测试 `test_update_document_invalid_status_422` — 验证传非法 status 返回 422
- [x] 4.5 编写测试 `test_update_chunk_invalid_status_422` — 验证传非法 chunk status 返回 422

## 5. 内存后端 create_document 不持久化修复

- [x] 5.1 修复 `app/api/v1/documents.py:create_document` 内存后端分支 — 当 `ingest_after_create=False` 时，在响应 `meta` 中增加 `warning` 提示内存模式下文档仅在入库后可见
- [x] 5.2 当 `ingest_after_create=True` 时（仍走入库路径），确保文档信息通过入库 pipeline 间接写入 chunk 元数据
- [x] 5.3 编写测试 `test_memory_create_document_no_ingest_warning` — 验证内存模式下不入库创建返回警告

## 6. 内存后端 list_documents 过滤参数静默忽略修复

- [x] 6.1 修复 `app/api/v1/documents.py:list_documents` 内存后端分支 — 收集 `source_type`、`parent_doc_id`、`root_doc_id`、`ingest_job_id`、`sort_by`、`sort_order` 中非 None 的参数名
- [x] 6.2 在响应 `meta` 中增加 `unsupported_filters` 字段列出未应用的参数（仅当参数被传入但未被应用时），同时在 debug 级别记录日志
- [x] 6.3 同步修复 `app/api/documents.py:list_documents` 遗留端点的相同问题（遗留端点只接受 category/status，无不支持过滤问题）
- [x] 6.4 编写测试 `test_memory_list_documents_unsupported_filters` — 验证传不支持的过滤参数时 meta 包含 unsupported_filters

## 7. 内存后端 ingest_document 信息缺失修复

- [x] 7.1 修复 `app/api/v1/documents.py:ingest_document` 内存后端分支 — 尝试从 chunk_store 获取已有文档信息补全 Document 对象的 title、source_type、source_hash、category 等字段
- [x] 7.2 若 chunk_store 中无该文档的 chunk，使用 doc_id 作为最小 fallback 并记录 warning 日志
- [x] 7.3 编写测试 `test_memory_ingest_document_info_completion` — 验证从 chunk 元数据补全的 Document 对象字段正确

## 8. 筛选项 category count 语义混用修复

- [x] 8.1 修复 `app/api/v1/search.py:search_filters` — 优先使用 document_repo 的分类统计作为 count；仅 document_repo 不可用时才回退到 chunk_store 统计
- [x] 8.2 移除 `max(doc_categories.get(category, 0), count)` 的混合取值逻辑，改用优先级回退策略
- [x] 8.3 编写测试 `test_search_filters_category_count_priority` — 验证 document_repo 可用时 count 来自文档统计

## 9. 代码风格清理

- [x] 9.1 修复 `app/api/v1/chunks.py:463` — 删除 `__import__("datetime")` 内联调用，改用文件顶部已有的 `datetime` 和 `timezone` 导入
- [x] 9.2 修复 `app/api/v1/ingest.py:job_to_dict:25` — 将 `or doc_id` 改为显式 `if doc_title is None or doc_title == ""` 判断，避免空标题被 doc_id 覆盖

## 10. 遗留端点同步修复

- [x] 10.1 检查 `app/api/documents.py` 所有端点，确认是否存在与 v1 相同的内存后端推导逻辑缺陷（遗留端点纯只读，无需要修复的逻辑）
- [x] 10.2 将本节各修复中对 v1 端点的改动，同步应用到 `app/api/documents.py` 对应逻辑（无需改动，遗留端点不涉及入库/枚举/创建）
- [x] 10.3 确保遗留端点在 deprecated 响应头之外，行为与 v1 端点一致

## 11. 回归验证

- [x] 11.1 运行全部现有测试 `pytest tests/ -v`，确保所有修复不破坏已有功能（47+114=161 全部通过）
- [x] 11.2 手动验证 `POST /ingest`（旧版）空 hash 场景行为正确（test_legacy_ingest_empty_hash_not_skipped 通过）
- [x] 11.3 手动验证 `POST /api/v1/search` 多分类检索结果完整性（TestMultiCategorySearch 全部通过）
- [x] 11.4 手动验证 `POST /api/v1/documents/upload` 重复上传不产生孤儿文件（test_upload_create_before_file_logic 通过）
- [x] 11.5 手动验证内存后端 `create_document`→`list_documents`→`ingest_document` 完整链路（相关测试全部通过）
- [x] 11.6 手动验证 `GET /api/v1/search/filters` 筛选项计数正确（test_category_count_priority_doc_repo 通过）
- [x] 11.7 手动验证枚举无效值返回 422 而非 500（TestInvalidEnumHandling 全部通过）
