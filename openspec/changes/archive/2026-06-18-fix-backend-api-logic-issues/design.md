## Context

代码审查发现后端接口存在 11 个逻辑缺陷，涉及去重判空、检索过滤、上传时序、枚举校验、内存后端持久化、代码风格等多个维度。所有修复均限定在 `app/api/` 层，不涉及数据库 schema、配置项或外部依赖变更。

当前状态：
- 后端双模式（PostgreSQL + 内存），旧 `/ingest`/`/search`/`/upload` 等端点标记为 deprecated 但仍在使用
- v1 端点通过 `app/api/v1/` 提供统一 `APIResponse`/`PaginatedResponse` 结构
- 去重依赖 `source_hash`（SHA256 内容指纹），上传和入库两层均有去重检查
- 检索通过 `retrieval_pipeline.search()` 执行双路检索 + RRF + Rerank

## Goals / Non-Goals

**Goals:**
- 修复空 `source_hash` 被误判为 `no_change` 的问题
- 修复多 `categories` 检索时结果不完整的问题
- 修复上传文件先落盘再查重可能产生孤儿文件的问题
- 修复 `DocStatus`/`ChunkStatus` 无效值直接 500 的问题
- 修复内存后端 `create_document` 不持久化的问题
- 修复内存后端 `list_documents` 过滤参数静默忽略的问题
- 修复内存后端 `ingest_document` 信息缺失的问题
- 修复筛选项 `category` count 语义混用的问题
- 同步修复遗留端点（`app/api/documents.py`）中的相同逻辑缺陷
- 清理 `__import__` 内联调用和 `or` 短路误判

**Non-Goals:**
- 不引入新的 API 端点或数据模型
- 不修改数据库 schema
- 不改变 retrieval pipeline 的公共接口（内部扩展除外）
- 不做大规模重构

## Decisions

### Decision 1: 空 hash 判重修复方案

**选择**: 在 `app/api/ingest.py:47` 添加 `if item.source_hash and existing.source_hash == item.source_hash` 显式判空。

**理由**: 
- 最小改动，仅增加一个条件
- 空字符串在 Python 中为 falsy，`if item.source_hash` 简洁且语义明确
- 若双方都为空，跳过 `no_change` 快速路径，继续执行正常入库流程

**替代方案**: 在 Document 模型层将 `source_hash` 默认值从 `""` 改为 `None`，然后使用 `is None` 判断。此方案改动面更大（影响序列化、数据库查询），风险高于收益。

### Decision 2: 多 categories 检索修复方案

**选择**: 在 `_execute_search` 中，对多 categories 情况，对每个 category 分别调用 `retrieval_pipeline.search()`，然后合并结果（按 chunk_id 去重，取最高分），再进入过滤和 enrich 流程。

**理由**:
- 不需要修改 `retrieval_pipeline.search()` 的接口（保持向后兼容）
- 每个 category 独立检索，确保各分类相关结果都能出现在候选集中
- 合并去重开销可控：每个 category 的 top_k 较小（`request.top_k * 10`），总候选量有限

**替代方案 A**: 修改 `retrieval_pipeline.search()` 接口支持多 category OR 过滤。此方案需改动 pipeline 内部及索引查询层，影响面大。

**替代方案 B**: 传 `None` 给 pipeline（不做 category 过滤），仅在后处理阶段按 categories 过滤。当某一 category 结果被挤出 top 候选时会丢失结果 → 这正是当前 bug。不采用。

### Decision 3: 上传时序修复方案

**选择**: 调整 `upload_document` 流程：先创建 Document 记录（预占位），再调用 `save_upload_file` 保存文件；若文件保存失败，删除预创建的 Document 记录回滚。

**理由**:
- 数据库操作先于文件系统操作，确保一致性
- 利用 `document_repo.create()` 的唯一索引约束作为并发保护
- 失败回滚简单可靠

**替代方案**: 在 `except DuplicateDocumentError` 中删除已上传的文件。不如预先占位方案优雅，且文件可能已被其他请求引用。

### Decision 4: 枚举校验修复方案

**选择**: 在 `update_document` 和 `update_chunk` 中用 try-except 包裹 `DocStatus(status)` 和 `ChunkStatus(chunk_status)`，捕获 `ValueError` 返回 422 JSON 错误响应。

**理由**:
- 最小改动，仅增加异常保护
- 422 是语义正确的 HTTP 状态码（Unprocessable Entity）
- 保持与 FastAPI 内置校验一致的错误风格

### Decision 5: 代码风格清理

**`__import__` 修复**: 直接用文件顶部已有的 `datetime` 和 `timezone` 导入。
**`or` 短路修复**: 改为 `if doc_title is None or doc_title == ""` 显式判断。

### Decision 6: 内存后端 `create_document` 不持久化修复

**选择**: 当 `document_repo is None`（内存模式）时，若 `ingest_after_create=True`，通过入库 pipeline 间接将文档信息写入 chunk 元数据；若 `ingest_after_create=False`，在响应中附带 `meta.warning` 提示内存模式下文档仅在入库后可见。

**理由**:
- 内存后端无文档存储层，无法直接持久化 Document 对象
- 入库 pipeline 会创建 chunk 并写入 chunk_store，chunk 的 metadata 携带文档信息
- 不入库时明确告知用户限制，而非静默丢弃

**替代方案**: 在内存后端用 dict 模拟 document_repo。改动面大，且与设计目标（内存后端为轻量开发模式）不符。

### Decision 7: 内存后端 `list_documents` 过滤参数静默忽略修复

**选择**: 内存后端路径中，对不支持的过滤参数（`source_type`、`parent_doc_id`、`root_doc_id`、`ingest_job_id`、`sort_by`、`sort_order`），在响应 `meta` 中增加 `unsupported_filters` 字段列出未应用的参数，并在 debug 级别记录日志。

**理由**:
- 不改变响应结构（仍返回数据），仅添加提示信息
- 帮助前端开发者理解内存模式的行为差异
- 无需实现完整的内存端过滤逻辑（超出本次修复范围）

### Decision 8: 筛选项 category count 语义混用修复

**选择**: `search_filters` 中优先使用 document_repo 的 category 统计作为筛选项 count；仅当 document_repo 不可用时才回退到 chunk_store 统计。不再使用 `max` 合并两个数据源。

**理由**:
- document_repo 的 category 统计覆盖所有文档（含尚无 chunk 的新文档），语义更完整
- chunk_store 统计作为 fallback 保证内存模式可用
- 消除两个不同统计口径混用的歧义

### Decision 9: 遗留端点同步修复

**选择**: `app/api/documents.py` 中存在与 v1 端点类似的内存后端推导逻辑和去重判断，逐一同步应用相同的修复。

**理由**:
- 旧端点虽标记 deprecated 但仍可被调用，应保持行为一致
- 修复改动量极小（多数与 v1 端点的修复模式一致）

## Risks / Trade-offs

- **[Risk] 多分类合并检索增加延迟**: 对 N 个 category 分别检索，耗时 ≈ N × 单次检索。→ **Mitigation**: 实际场景中多分类请求很少（典型为 1-3 个），top_k 不大；可在后续版本中引入并行检索优化。
- **[Risk] 上传流程预占位后的回滚复杂度**: 如果文件保存失败需删除已创建的 Document。→ **Mitigation**: Document 删除操作简单可靠；若删除也失败（极低概率），`status='pending'` 的孤儿文档可通过定期清理任务处理。
- **[Trade-off] 内存后端信息补全依赖 chunk_store**: 内存后端从 chunk_store 获取已有文档信息来构建 Document 对象。如果没有 chunk，仍无法获取完整信息。→ 接受此限制，内存后端本身是开发/测试用途。
- **[Trade-off] 内存后端不支持完整过滤**: `list_documents` 内存路径不支持 `source_type`/`parent_doc_id` 等高级过滤，仅在响应中标注。→ 在 meta 中提示后，前端可据此调整 UI（如隐藏不可用的过滤控件），不阻塞功能。
- **[Risk] 遗留端点修复遗漏**: `app/api/documents.py` 中有多处代码与 v1 相似但独立维护。→ **Mitigation**: tasks 中单独列出遗留端点同步任务，逐一对照修复。
