## Why

全面代码审查发现后端接口存在 3 个严重逻辑缺陷（空 hash 误判导致跳过合法入库、多分类检索结果不完整、上传与查重时序倒置产生孤儿文件）、4 个中等稳定性问题（枚举无效值直接 500、内存后端文档不持久化、内存后端入库信息缺失、内存后端过滤参数静默忽略）和 4 个代码质量问题（`__import__` 内联调用、`or` 短路覆盖空标题、筛选项计数语义混用、遗留端点重复逻辑未同步修复）。这些问题直接破坏数据完整性、检索准确性和 API 稳定性，需在用户大规模使用前修复。

## What Changes

### 严重问题

- **修复空 source_hash 被误判为 no_change**：在 `POST /ingest`（旧版）中，当双方 source_hash 均为空字符串时不再跳过入库；同时在旧版 `app/api/documents.py` 遗留端点中同步修复相同逻辑
- **修复多 categories 检索不完整**：当 `SearchFilters.categories` 包含多个值时，确保每个 category 都能被 retrieval pipeline 覆盖（对每个 category 执行检索后合并去重）
- **修复上传时序导致的孤儿文件**：调整 `POST /api/v1/documents/upload` 中查重与文件写入的顺序，先创建文档记录再落盘，创建失败则回滚文件

### 中等问题

- **修复枚举无效值导致 500**：`DocStatus(status)` 和 `ChunkStatus(status)` 调用增加异常捕获，无效值时返回 422 Validation Error 而非 500
- **修复内存后端 `create_document` 不持久化**：当 `document_repo is None`（内存模式）且 `ingest_after_create=False` 时，创建的 Document 对象被丢弃。修复方案：在不入库时，至少将文档信息写入 chunk_store 的元数据中，或明确返回警告
- **修复内存后端 `ingest_document` 信息缺失**：从 chunk_store 中获取已有文档信息补全 Document 对象的 title、source_type、source_hash、category 等字段
- **修复内存后端 `list_documents` 过滤参数静默忽略**：`source_type`、`parent_doc_id`、`root_doc_id`、`ingest_job_id`、`sort_by`、`sort_order` 参数在内存后端被接收但完全不用，应在不支持时返回提示或至少记录日志

### 代码质量

- **修复 `__import__` 内联调用**：用顶部导入替代 [app/api/v1/chunks.py:463](app/api/v1/chunks.py#L463) 中的 `__import__("datetime")` 动态导入
- **修复 `or` 短路覆盖空标题**：`job_to_dict` 中使用显式 `is None` 判断替代 `or` 短路
- **修复筛选项 category count 语义混用**：`search_filters` 中将 chunk 统计和文档统计的计数混用 `max` 合并，改为区分标注或仅使用单一数据源
- **同步修复遗留端点相同逻辑缺陷**：`app/api/documents.py` 中存在与 v1 端点相同的内存后端推导逻辑，同步应用修复

## Capabilities

### New Capabilities

无。本次为纯缺陷修复，不引入新能力。

### Modified Capabilities

- **document-deduplication**: 上传查重时序修正——文件查重检查应在文件落盘前完成并预占位，杜绝孤儿文件；对应 spec 中的 Scenario "上传已存在的文件"需补充竞态条件下的行为约束
- **hybrid-retrieval**: 多分类检索行为修正——当 filters.categories 包含多个值时，检索策略调整为对每个 category 分别检索后合并，而非仅传第一个或传 None；筛选项计数改为仅使用单一可靠数据源
- **document-incremental-update**: 增量更新判重逻辑修正——source_hash 为空时不视为 "no_change"，添加显式空值检查；旧版 `/ingest` 同步修复
- **document-management-api**: 内存后端行为修正——`list_documents` 不支持过滤参数时主动告知；`create_document` 确保文档不丢失

## Impact

- **受影响文件**:
  - `app/api/ingest.py` — 空 hash 判重修复
  - `app/api/documents.py` — 遗留端点同步修复（空 hash 判重 + 内存后端补全）
  - `app/api/v1/documents.py` — 上传时序修复 + 枚举校验 + 内存后端补全（create/list/ingest 三处）
  - `app/api/v1/search.py` — 多分类检索修复 + 筛选项计数修复
  - `app/api/v1/chunks.py` — 枚举校验 + `__import__` 清理
  - `app/api/v1/ingest.py` — `job_to_dict` 空标题修复
- **API 兼容性**: 无 **BREAKING** 变更；所有修改为行为修正，不影响现有请求格式和成功响应格式
- **回滚计划**: 每个修复独立提交，可通过 `git revert` 单独回滚；修复不涉及数据库 schema 变更
- **测试影响**: 需为每个修复补充对应的单元测试和/或集成测试用例
