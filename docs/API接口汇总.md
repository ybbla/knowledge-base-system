# Knowledge Base System — API 接口汇总

> 生成日期：2026-06-18
> 版本：0.3.0
> 所有 `/api/v1` 接口返回统一的 `{ data, meta, error }` 结构。

---

## 一、系统健康检查 — `/api/v1/health`

| 方法 | 路径 | 功能 | 说明 |
|------|------|------|------|
| `GET` | `/api/v1/health/live` | 进程存活检查 | 始终返回 200 `{ status: "ok" }` |
| `GET` | `/api/v1/health/ready` | 核心依赖就绪检查 | 检查 document_repo, element_repo, chunk_store, vector_index, bm25_index, asset_store；任一不可用返回 503 |
| `GET` | `/api/v1/health/dependencies` | 依赖状态详情 | 返回各依赖状态（backend, embedding, llm 等），隐藏敏感信息 |

**响应结构：**
- `/live`: `{ data: { status: "ok" }, meta: { service, version } }`
- `/ready`: `{ data: { status: "ok" | "degraded", checks: { ... } }, meta: { backend } }`
- `/dependencies`: `{ data: { dependencies: { backend, document_repo, element_repo, chunk_store, vector_index, bm25_index, embedding, llm, asset_store } } }`

---

## 二、文档管理 — `/api/v1/documents`

| 方法 | 路径 | 功能 | 参数 |
|------|------|------|------|
| `GET` | `/api/v1/documents` | 文档分页列表，支持多条件筛选和排序 | Query: `page`, `page_size`, `sort_by`, `sort_order`, `keyword`, `source_type`, `status`, `category`, `parent_doc_id`, `root_doc_id`, `ingest_job_id` |
| `POST` | `/api/v1/documents` | 创建文档（URI 来源），可选立即入库 | Query: `title`(必), `source_type`(必), `source_uri`(必), `source_hash`, `category`, `metadata`(JSON), `ingest_after_create` |
| `POST` | `/api/v1/documents/upload` | 上传文件并创建文档，可选立即入库 | Form: `file`(必), `title`, `category`; Query: `ingest_after_create`, `mode` |
| `GET` | `/api/v1/documents/{doc_id}` | 文档详情（含统计信息） | Path: `doc_id` |
| `GET` | `/api/v1/documents/{doc_id}/elements` | 文档解析元素分页列表 | Path: `doc_id`; Query: `page`, `page_size` |
| `PATCH` | `/api/v1/documents/{doc_id}` | 更新文档（支持乐观锁） | Path: `doc_id`; Query: `title`, `category`, `status`, `source_uri`, `source_hash`, `expected_version`, `metadata`(JSON) |
| `DELETE` | `/api/v1/documents/{doc_id}` | 软删除文档（级联知识块+索引） | Path: `doc_id` |
| `POST` | `/api/v1/documents/{doc_id}/restore` | 恢复软删除的文档 | Path: `doc_id` |
| `POST` | `/api/v1/documents/{doc_id}/ingest` | 对文档触发入库/增量更新/强制重建 | Path: `doc_id`; Query: `mode` (incremental / force) |

**响应结构：**
- 列表：`PaginatedResponse { data: [...], meta: { page, page_size, total, total_pages } }`
- 单条：`APIResponse { data: { doc_id, title, source_type, source_uri, source_hash, category, version, status, parent_doc_id, root_doc_id, ingest_job_id, created_at, updated_at, metadata, chunk_count, element_count, asset_count, index_summary } }`
- 上传重复：`data.duplicate=true, data.existing_doc_id`
- 入库触发：`data.job_id, data.doc_id, data.mode, data.job`

**错误码：** `DOCUMENT_NOT_FOUND`(404), `DOCUMENT_DUPLICATE`(409), `DOCUMENT_VERSION_CONFLICT`(409)

---

## 三、知识块管理 — `/api/v1/chunks`

| 方法 | 路径 | 功能 | 参数 |
|------|------|------|------|
| `GET` | `/api/v1/chunks` | 知识块分页列表，多条件筛选 | Query: `page`, `page_size`, `sort_by`, `sort_order`, `keyword`, `doc_id`, `doc_version`, `category`, `knowledge_type`, `status`, `index_status`, `ingest_job_id`, `has_assets`, `has_sources` |
| `POST` | `/api/v1/chunks` | 创建人工知识块，可选创建后索引 | Query: `doc_id`(必), `content`(必), `title`, `knowledge_type`, `category`, `metadata`(JSON), `index_after_create` |
| `POST` | `/api/v1/chunks/batch/reindex` | 批量重建知识块索引 | Body: `{ chunk_ids: [...] }` |
| `POST` | `/api/v1/chunks/batch` | 批量状态操作 | Body: `{ action: delete|restore|update_status, chunk_ids: [...], status? }` |
| `GET` | `/api/v1/chunks/{chunk_id}` | 知识块详情（含完整内容+来源+资源） | Path: `chunk_id` |
| `PATCH` | `/api/v1/chunks/{chunk_id}` | 更新知识块，内容变化时可选重建索引 | Path: `chunk_id`; Query: `title`, `content`, `category`, `knowledge_type`, `status`, `metadata`(JSON), `reindex` |
| `DELETE` | `/api/v1/chunks/{chunk_id}` | 软删除知识块，同步索引 | Path: `chunk_id` |
| `POST` | `/api/v1/chunks/{chunk_id}/restore` | 恢复软删除的知识块 | Path: `chunk_id` |
| `POST` | `/api/v1/chunks/{chunk_id}/reindex` | 重建单个知识块的向量+BM25索引 | Path: `chunk_id` |

**响应结构：**
- 列表条目：`{ chunk_id, doc_id, doc_title, doc_version, title, content_preview, knowledge_type, category, status, index_status, indexed_at, index_error, asset_count, source_count, ingest_job_id, metadata }`
- 详情：`{ ...完整 content, content_hash, asset_refs, source_refs }`

**错误码：** `CHUNK_NOT_FOUND`(404), `DOCUMENT_NOT_FOUND`(404)

---

## 四、检索 — `/api/v1/search`

| 方法 | 路径 | 功能 | 请求体 |
|------|------|------|------|
| `POST` | `/api/v1/search` | 标准混合检索，支持完整过滤和 LLM Rerank | `{ query, top_k(1-100), filters: { doc_ids, categories, knowledge_types, chunk_status, index_status, source_types, doc_status, created_after, created_before }, options: { rewrite, hybrid, rerank, highlight, include_assets, include_sources, include_score_components } }` |
| `POST` | `/api/v1/search/debug` | 调试检索，返回各阶段候选和评分 | 同上 |
| `GET` | `/api/v1/search/filters` | 返回可用筛选项（分类/来源/知识类型/状态） | — |

**响应结构：**
```json
{
  "data": {
    "search_id": "...",
    "query": "...",
    "rewritten_query": "...",
    "total_count": 5,
    "results": [{ "chunk_id", "doc_id", "doc_title", "title", "content", "score", "category", "knowledge_type", "score_components": { "vector", "bm25", "rerank" }, "asset_refs", "source_refs", "metadata", "highlight" }]
  },
  "meta": { "search_id", "query", "rewritten_query", "total_count", "filters", "options" }
}
```

**调试模式额外字段：** `rewrite`, `vector_candidates`, `bm25_candidates`, `fused_candidates`, `rerank_results`, `stats`, `errors`

---

## 五、入库任务管理 — `/api/v1/ingest/jobs`

| 方法 | 路径 | 功能 | 参数 |
|------|------|------|------|
| `GET` | `/api/v1/ingest/jobs` | 入库任务分页列表，支持筛选 | Query: `page`, `page_size`, `status`, `doc_id`, `mode`, `keyword` |
| `GET` | `/api/v1/ingest/jobs/{job_id}` | 入库任务详情 | Path: `job_id` |
| `POST` | `/api/v1/ingest/jobs/{job_id}/retry` | 重试失败任务 | Path: `job_id`（仅 status=failed 可重试） |
| `POST` | `/api/v1/ingest/jobs/{job_id}/cancel` | 取消等待中的任务 | Path: `job_id`（仅 pending 可取消） |

**响应字段：** `{ job_id, doc_id, doc_ids, doc_title, doc_count, mode, status, stage, progress, chunk_count, asset_count, error, created_at, started_at, finished_at }`

**错误码：** `INGEST_JOB_NOT_FOUND`(404), `INGEST_JOB_CONFLICT`(409)

---

## 六、旧版接口（已废弃，兼容期内可用）

所有旧版接口均在响应头中包含 `X-Deprecated`，并记录 WARNING 日志。

### 6.1 文档 — `/documents`

| 方法 | 路径 | 替代接口 |
|------|------|------|
| `GET` | `/documents` | `GET /api/v1/documents` |
| `GET` | `/documents/{doc_id}` | `GET /api/v1/documents/{doc_id}` |
| `GET` | `/documents/{doc_id}/elements` | `GET /api/v1/documents/{doc_id}/elements` |
| `GET` | `/documents/{doc_id}/chunks` | `GET /api/v1/chunks?doc_id=...` |

### 6.2 上传 — `/upload`

| 方法 | 路径 | 替代接口 |
|------|------|------|
| `POST` | `/upload` | `POST /api/v1/documents/upload` |

参数：Form `file`(必), `title`, `category`

### 6.3 入库 — `/ingest`

| 方法 | 路径 | 替代接口 |
|------|------|------|
| `POST` | `/ingest` | `POST /api/v1/documents/upload` (新建) 或 `POST /api/v1/documents/{doc_id}/ingest` (已有文档) |
| `GET` | `/ingest/{job_id}` | `GET /api/v1/ingest/jobs/{job_id}` |

POST `/ingest` 请求体：`{ documents: [{ title, source_type, source_uri, source_hash, category, doc_id? }], options: {} }`

### 6.4 检索 — `/search`

| 方法 | 路径 | 替代接口 |
|------|------|------|
| `POST` | `/search` | `POST /api/v1/search` |

请求体：`{ query, top_k, filters: { category? } }`

---

## 七、统一错误结构

所有 `/api/v1` 错误响应格式：

```json
{
  "data": null,
  "meta": {},
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "文档 xxx 不存在",
    "details": null
  }
}
```

### 错误码汇总

| 错误码 | HTTP 状态 | 说明 |
|------|------|------|
| `DOCUMENT_NOT_FOUND` | 404 | 文档不存在 |
| `DOCUMENT_DUPLICATE` | 409 | 相同 source_hash 的活跃文档已存在 |
| `DOCUMENT_VERSION_CONFLICT` | 409 | 乐观锁版本冲突 |
| `CHUNK_NOT_FOUND` | 404 | 知识块不存在 |
| `INGEST_JOB_NOT_FOUND` | 404 | 入库任务不存在 |
| `INGEST_JOB_CONFLICT` | 409 | 入库任务状态冲突（如重试非失败任务） |
| `VALIDATION_ERROR` | 400 | 请求参数校验失败 |
| `INTERNAL_ERROR` | 500 | 内部错误 |
| `SERVICE_UNAVAILABLE` | 503 | 服务不可用 |

---

## 八、接口统计

| 分组 | 接口数 | 前缀 |
|------|------|------|
| 健康检查 (v1) | 3 | `/api/v1/health` |
| 文档管理 (v1) | 9 | `/api/v1/documents` |
| 知识块管理 (v1) | 9 | `/api/v1/chunks` |
| 检索 (v1) | 3 | `/api/v1/search` |
| 入库任务 (v1) | 4 | `/api/v1/ingest/jobs` |
| **活跃 v1 接口合计** | **28** | — |
| 旧版文档 | 4 | `/documents` [已废弃] |
| 旧版上传 | 1 | `/upload` [已废弃] |
| 旧版入库 | 2 | `/ingest` [已废弃] |
| 旧版检索 | 1 | `/search` [已废弃] |
| **总计** | **36** | — |
