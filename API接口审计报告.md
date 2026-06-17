# API 接口审计报告 — 缺失与冗余分析

> 审计日期：2026-06-16 | 方法：对比后端 FastAPI 路由定义、Pydantic 请求/响应模型 与 前端 `api.js` + 6 个组件实际调用

---

## 一、API 端点全景

| 方法 | 路径 | 后端文件 | 前端调用方 | 用途 |
|------|------|----------|-----------|------|
| `GET` | `/health` | `main.py:36` | `app.js:56`、`dashboard.js:14` | 健康检查 |
| `POST` | `/upload` | `upload.py:23` | `documents.js:307` | 文件上传 |
| `POST` | `/ingest` | `ingest.py:27` | `documents.js:312`、`ingestion.js:242` | 提交入库 |
| `GET` | `/ingest/{job_id}` | `ingest.py:108` | `ingestion.js:72` | 任务状态 |
| `POST` | `/search` | `search.py:15` | `search.js:107` | 知识检索 |
| `GET` | `/documents` | `documents.py:73` | `documents.js:19`、`dashboard.js:25` | 文档列表 |
| `GET` | `/documents/{doc_id}` | `documents.py:128` | `document-detail.js:22` | 文档详情 |
| `GET` | `/documents/{doc_id}/elements` | `documents.py:171` | `document-detail.js:23` | 解析元素 |
| `GET` | `/documents/{doc_id}/chunks` | `documents.py:183` | `document-detail.js:24` | 知识块列表 |

---

## 二、逐端点审计

### 2.1 `GET /health`

**后端定义：**
```python
@app.get("/health")
async def health():
    return {"status": "ok"}
```

**前端调用：**
```js
// app.js:56
const health = await API.healthCheck();
UI.setBackendStatus(health?.status === 'ok', '服务正常');

// dashboard.js:14
const health = await API.healthCheck();
healthOk = health && health.status === 'ok';
```

**判定：**

| 项目 | 状态 |
|------|------|
| 请求参数 | ✅ 无参数，正确 |
| 响应字段 `status` | ✅ 前后端一致 |
| 响应字段 `status` 值 | ✅ `"ok"` 字符串匹配 |

**问题：**
- ⚠️ **缺失**：健康检查仅返回 `{"status": "ok"}`，前端仪表盘展示的"向量检索引擎"、"全文检索引擎"、"LLM 服务"状态全部显示 `—`。建议扩展为：

```json
{
  "status": "ok",
  "version": "0.1.0",
  "backend": "postgres",
  "services": {
    "database": "ok",
    "milvus": "ok",
    "minio": "ok",
    "llm": "ok"
  }
}
```

### 2.2 `POST /upload`

**后端请求：**
```python
file: UploadFile = File(...)
title: str | None = Form(default=None)
category: str = Form(default="通用")
```

**后端响应（正常）：**
```python
{
    "source_uri": str,
    "source_hash": str,
    "doc_id": str,
    "file_name": str,
    "size": int,
    "title": str,
    "category": str,
}
```

**后端响应（去重命中）：**
```python
{
    "duplicate": True,         # ← 仅去重时存在
    "existing_doc_id": str,    # ← 仅去重时存在
    "source_uri": str,
    "source_hash": str,
    "doc_id": str,
    "file_name": str,
    "size": int,
    "title": str,
    "category": str,
}
```

**前端调用：**
```js
// documents.js:307
const result = await API.uploadFile(selectedFile, title, category);
// 只读取 result.source_uri
```

**前端发送：** `FormData { file, title?, category? }`

**判定：**

| 项目 | 状态 |
|------|------|
| 请求参数 `file` | ✅ 前后端一致 |
| 请求参数 `title` | ✅ 可选，前后端一致 |
| 请求参数 `category` | ✅ 默认"通用"，前后端一致 |
| 响应字段 `source_uri` | ✅ 前端使用 |
| 响应字段 `source_hash` | ⚠️ 后端返回但前端未传递给 `/ingest`（见 2.3） |
| 响应字段 `doc_id` | ⚠️ 后端返回但前端从未使用 |
| 响应字段 `file_name` | ⚠️ 后端返回但前端从未使用 |
| 响应字段 `size` | ⚠️ 后端返回但前端从未使用 |
| 响应字段 `title` | ⚠️ 后端返回但前端用自己构造的 title |
| 响应字段 `category` | ⚠️ 后端返回但前端用自己构造的 category |
| 响应字段 `duplicate` | ⚠️ 前端未处理去重情况 |
| 响应字段 `existing_doc_id` | ⚠️ 前端未处理 |

**问题：**

| ID | 严重 | 问题 |
|----|------|------|
| **API-U-01** | 🔴 P0 | `source_hash` 已返回但前端未传给 `/ingest`，导致入库必填字段缺失（见 2.3） |
| API-U-02 | 🟡 P2 | `duplicate` 字段前端未处理 — 上传重复文件时无提示 |
| API-U-03 | 🟢 P3 | 响应中 `doc_id`/`file_name`/`size`/`title`/`category` 5 个字段前端未消费（虽然后端自用合理） |

### 2.3 `POST /ingest` 🔴

**后端请求模型：**
```python
class IngestDocument(BaseModel):
    title: str
    source_type: str
    source_uri: str
    source_hash: str          # ← 必填！无默认值
    category: str = "通用"
    doc_id: str | None = None

class IngestRequest(BaseModel):
    documents: list[IngestDocument]
    options: dict[str, Any] = Field(default_factory=dict)
```

**后端响应：**
```python
{
    "job_id": str | list[str],
    "status": "accepted",
    "doc_ids": list[str],
    "warnings": list[dict],
}
```

**前端调用（上传流程 `documents.js:312-317`）：**
```js
const ingestResult = await API.submitIngest([{
    title: title || selectedFile.name,
    source_type: detectSourceType(selectedFile.name),
    source_uri: result.source_uri,
    category: category,
    // ❌ 缺少 source_hash！
}]);
```

**前端调用（手动提交 `ingestion.js:242-247`）：**
```js
const result = await API.submitIngest([{
    title: title || uri.split('/').pop() || '未命名文档',
    source_type: sourceType,
    source_uri: uri,
    category: category,
    // ❌ 缺少 source_hash！且手动输入 URI 无法计算 hash
}]);
```

**判定：**

| 项目 | 状态 |
|------|------|
| 请求字段 `title` | ✅ |
| 请求字段 `source_type` | ✅ |
| 请求字段 `source_uri` | ✅ |
| 请求字段 `source_hash` | 🔴 **前端未传递** — 必填字段缺失，Pydantic 校验会返回 422 |
| 请求字段 `category` | ✅ |
| 请求字段 `doc_id` | ⚠️ 前端从未传（增量更新功能前端未对接） |
| 响应字段 `job_id` | ✅ 前端存储到 localStorage |
| 响应字段 `status` | ✅ |
| 响应字段 `doc_ids` | ⚠️ 前端未使用 |
| 响应字段 `warnings` | ⚠️ 前端未展示 |

**问题：**

| ID | 严重 | 问题 |
|----|------|------|
| **API-I-01** | 🔴 P0 | `source_hash` 必填但前端两处调用均未传递。**这是一个阻塞性 bug**：前端上传→入库流程会收到 422 错误 |
| **API-I-02** | 🔴 P0 | `ingestion.js` 手动入库模态框无法获取 `source_hash`（未上传文件直接填 URI，无法计算哈希）。需要改为：要么先上传再入库，要么要求传入 hash |
| API-I-03 | 🟡 P2 | 增量更新（`doc_id`）前端未对接 — 文档更新功能在前端不可用 |
| API-I-04 | 🟡 P2 | `warnings`（去重提示、no_change 提示）前端未展示给用户 |

### 2.4 `GET /ingest/{job_id}`

**后端响应：**
```python
{
    "job_id": str,
    "status": str,
    "doc_ids": list[str],
    "chunk_count": int,
    "asset_count": int,
    "error": str | None,
    "started_at": str | None,     # ← ISO 格式
    "finished_at": str | None,    # ← 后端字段名
}
```

**前端读取（`ingestion.js:122-164`）：**
```js
const docCount = job.doc_count || job.doc_ids?.length || 0;
const chunkCount = job.chunk_count ?? '—';
const assetCount = job.asset_count ?? '—';
const error = job.error || '';
const startedAt = job.started_at;
const completedAt = job.completed_at;  // ← 前端读 completed_at
```

**判定：**

| 项目 | 状态 |
|------|------|
| `job_id` | ✅ |
| `status` | ✅ |
| `doc_ids` | ✅ `job.doc_ids?.length` |
| `chunk_count` | ✅ |
| `asset_count` | ✅ |
| `error` | ✅ |
| `started_at` | ✅ |
| `finished_at` vs `completed_at` | 🔴 **字段名不匹配** — 后端返回 `finished_at`，前端读 `completed_at` |
| `doc_count` | ⚠️ 前端读 `job.doc_count` 但后端不返回此字段，fallback 到 `doc_ids.length` |

**问题：**

| ID | 严重 | 问题 |
|----|------|------|
| **API-J-01** | 🟡 P1 | `finished_at` ↔ `completed_at` 字段名不一致。前端 `UI.formatTime(completedAt)` 始终显示 `—`，因为 `completedAt` 为 `undefined` |
| API-J-02 | 🟢 P3 | `warnings` 字段后端不返回但前端尝试读取 `job.warnings` |

### 2.5 `POST /search`

**后端请求：**
```python
class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    filters: dict = Field(default_factory=dict)
```

**后端响应：** `SearchResult.model_dump(mode="json")`
```python
{
    "search_id": str,
    "query": str,
    "rewritten_query": str,
    "total_count": int,
    "results": [
        {
            "chunk_id": str,
            "title": str,
            "content": str,
            "score": float,
            "category": str,
            "knowledge_type": str,
            "score_components": {"vector": float, "bm25": float, "rerank": float},
            "asset_refs": [...],
            "source_refs": [...],
            "metadata": {...},
        }
    ],
}
```

**前端调用：**
```js
// search.js:107
lastResult = await API.search(query, topK, filters);
// 发送: {query, top_k: topK, filters}
```

**前端读取（`search.js:121-265`）：**
```js
result.results         // ✅
result.total_count     // ✅
result.rewritten_query // ✅
result.search_id       // ✅
// 每个 item:
item.chunk_id          // ✅
item.title             // ✅
item.content           // ✅
item.score             // ✅
item.score_components  // ✅ (vector/bm25/rerank)
item.knowledge_type    // ✅
item.category          // ✅
item.source_refs       // ✅ (doc_id, source_location.page, source_location.section_path)
item.asset_refs        // ✅ (asset_refs.length)
```

**判定：**

| 项目 | 状态 |
|------|------|
| 请求 `query` | ✅ |
| 请求 `top_k` | ✅ (前端发送 `top_k`，后端接收 `top_k`) |
| 请求 `filters.category` | ✅ 后端读取 `request.filters.get("category")` |
| 响应全部字段 | ✅ 前后端完全一致 |
| 前端 `topK` 拼写 | ⚠️ 前端用 `topK`(camelCase)，API 发送时转为 `top_k`(snake_case)，正确 |

> **结论：`POST /search` 是前后端对接最完美的端点，无任何问题。**

### 2.6 `GET /documents`

**后端响应：**
```python
# PG 后端:
{"documents": [_doc_to_dict(d) for d in docs], "total": len(docs)}

# 内存后端:
{"documents": [...], "total": len(docs)}
```

**`_doc_to_dict` 返回字段：**
```
doc_id, title, source_type, source_uri, source_hash, category,
version, status, parent_doc_id, root_doc_id, ingest_job_id,
created_at, updated_at, metadata
```

**前端调用：**
```js
// documents.js:19
const result = await API.listDocuments();
docs = Array.isArray(result) ? result : (result?.documents || []);
```

**前端读取：**
```js
doc.doc_id || doc.id       // ⚠️ 兼容了 doc.id（后端不返回）
doc.title || doc.file_name  // ⚠️ 兼容了 doc.file_name（后端不返回）
doc.source_type             // ✅
doc.category                // ✅
doc.status                  // ✅
doc.created_at              // ✅
```

**判定：**

| 项目 | 状态 |
|------|------|
| 响应格式 | ✅ 前端兼容数组和 `{documents}` 两种格式 |
| `doc_id` | ✅ |
| `title` | ✅ |
| `source_type` | ✅ |
| `category` | ✅ |
| `status` | ✅ |
| `created_at` | ✅ |
| 查询参数 `category` | ⚠️ 后端支持但前端从未传 |
| 查询参数 `status` | ⚠️ 后端支持但前端在客户端做过滤 |
| 分页 | ⚠️ 后端不支持分页，前端做客户端分页（`pageSize=15`） |

**问题：**

| ID | 严重 | 问题 |
|----|------|------|
| API-D-01 | 🟡 P2 | 无服务端分页 — 文档量大时性能问题。后端应支持 `?offset=0&limit=20` |
| API-D-02 | 🟡 P2 | 前端兼容 `doc.id` 和 `doc.file_name` 字段，但这些字段后端从不返回（防御性代码，无实际影响） |
| API-D-03 | 🟢 P3 | 前端在客户端做 `status` 过滤（`documents.js:138`），而后端已支持 `?status=` 查询参数，应改用服务端过滤 |

### 2.7 `GET /documents/{doc_id}`

**后端响应：** `_doc_to_dict(doc)` — 14 个字段

**前端读取（`document-detail.js:47-75`）：**
```js
doc.doc_id || doc.id     // ⚠️ 兼容 doc.id
doc.title || doc.file_name  // ⚠️ 兼容 doc.file_name
doc.source_type
doc.category
doc.status
doc.version
doc.created_at
doc.updated_at
```

**判定：** ✅ 无问题。所有前端需要的字段后端都返回。

### 2.8 `GET /documents/{doc_id}/elements`

**后端响应：** `{elements: [_element_to_dict(el) ...], total: N}`

**`_element_to_dict` 返回字段：**
```
element_id, doc_id, doc_version, parent_element_id, sequence_order,
element_type, text, structured_data, asset_ids, embedded_doc_id,
source_location, metadata
```

**前端读取（`document-detail.js:124-136`）：**
```js
el.sequence_order
el.text
el.element_type
el.source_location?.page
```

**判定：** ✅ 无问题。前端只用了 4 个字段，但后端返回完整数据合理。

### 2.9 `GET /documents/{doc_id}/chunks`

**后端响应：** `{chunks: [_chunk_to_dict(c) ...], total: N}`

**前端读取（`document-detail.js:151-164`）：**
```js
chunk.title
chunk.knowledge_type
chunk.content
chunk.index_status
chunk.category
chunk.asset_refs?.length
```

**判定：** ✅ 无问题。

---

## 三、前后端对接问题汇总

### 🔴 P0 — 阻塞性

| ID | 端点 | 问题 | 影响 |
|----|------|------|------|
| **API-I-01** | `POST /ingest` | 前端不传 `source_hash` 必填字段 | 前端上传→入库流程收到 422，入库完全不可用 |
| **API-I-02** | `POST /ingest` | 手动入库模态框无法获取 `source_hash` | 手动入库功能不可用 |

### 🟡 P1 — 功能性

| ID | 端点 | 问题 | 影响 |
|----|------|------|------|
| **API-J-01** | `GET /ingest/{job_id}` | `finished_at` ↔ `completed_at` 字段名不匹配 | 任务完成时间始终显示 `—` |

### 🟡 P2 — 体验性

| ID | 端点 | 问题 | 影响 |
|----|------|------|------|
| API-U-02 | `POST /upload` | 去重响应 `duplicate` 字段前端未处理 | 上传重复文件无提示 |
| API-I-03 | `POST /ingest` | 增量更新（`doc_id`）前端未对接 | 文档更新功能不可用 |
| API-I-04 | `POST /ingest` | `warnings` 前端未展示 | 去重/跳过提示不可见 |
| API-D-01 | `GET /documents` | 无服务端分页 | 文档量大时性能下降 |
| API-H-01 | `GET /health` | 缺少服务状态详情 | 仪表盘状态面板大量 `—` |

### 🟢 P3 — 优化性

| ID | 端点 | 问题 |
|----|------|------|
| API-U-03 | `POST /upload` | 响应中 5 个字段前端未消费 |
| API-J-02 | `GET /ingest/{job_id}` | `warnings` 字段读取但后端不返回 |
| API-D-02 | `GET /documents` | 前端兼容 `doc.id`/`doc.file_name`（防御性代码） |
| API-D-03 | `GET /documents` | 前端客户端过滤替代了服务端过滤 |

---

## 四、缺失端点分析

以下功能在枚举/模型中已预留，但无对应 API：

| 功能 | 应有端点 | 状态 | 影响 |
|------|---------|------|------|
| 文档删除 | `DELETE /documents/{doc_id}` | ❌ 缺失 | `DocStatus.deleted` 枚举无入口 |
| 知识块删除 | `DELETE /chunks/{chunk_id}` | ❌ 缺失 | `ChunkStatus.deleted` 枚举无入口 |
| 系统状态详情 | `GET /health` 扩展 | ❌ 缺失 | 仪表盘无法展示后端类型/服务状态 |
| 文档统计 | `GET /documents/stats` | ❌ 缺失 | 仪表盘知识块数显示 `—` |
| 批量删除 | `DELETE /documents` | ❌ 缺失 | 批量管理不可用 |

---

## 五、冗余分析

### 请求模型冗余

| 位置 | 字段 | 判定 |
|------|------|------|
| `IngestDocument.source_hash` | 必填但前端不传 | ⚠️ 不是字段冗余，是前端 bug |
| `IngestDocument.doc_id` | 增量更新用，前端未对接 | ⚠️ 预留功能 |
| `IngestRequest.options` | 后端接收但仅透传，前端不传 | ⚠️ 预留扩展点 |
| `SearchRequest.filters` | 仅取 `category`，其余 key 被忽略 | ⚠️ 预留扩展点 |

### 响应字段冗余

| 端点 | 字段 | 前端使用？ | 判定 |
|------|------|-----------|------|
| `POST /upload` | `doc_id` | ❌ 不使用 | 🟢 合理（后端自用） |
| `POST /upload` | `file_name` | ❌ 不使用 | 🟢 合理（后端自用） |
| `POST /upload` | `size` | ❌ 不使用 | 🟢 合理（调试/日志） |
| `POST /upload` | `title` | ❌ 不使用 | 🟢 合理（后端回显） |
| `POST /upload` | `category` | ❌ 不使用 | 🟢 合理（后端回显） |
| `GET /documents/*` | `source_uri` | ❌ 不展示 | 🟢 合理（调试用） |
| `GET /documents/*` | `source_hash` | ❌ 不展示 | 🟢 合理（调试用） |
| `GET /documents/*` | `parent_doc_id` | ❌ 不展示 | 🟢 合理（嵌入文档场景） |
| `GET /documents/*` | `root_doc_id` | ❌ 不展示 | 🟢 合理（嵌入文档场景） |
| `GET /documents/*` | `ingest_job_id` | ❌ 不展示 | 🟢 合理（调试用） |
| `GET /documents/*/elements` | `element_id` | ❌ 不展示 | 🟢 合理（溯源用） |
| `GET /documents/*/elements` | `structured_data` | ❌ 不展示 | 🟢 合理（表格数据） |
| `GET /documents/*/elements` | `asset_ids` | ❌ 不展示 | 🟢 合理（资源关联） |
| `GET /documents/*/chunks` | `content_hash` | ❌ 不展示 | 🟢 合理（完整性校验） |
| `GET /documents/*/chunks` | `indexed_at` | ❌ 不展示 | 🟢 合理（调试用） |
| `GET /documents/*/chunks` | `index_error` | ❌ 不展示 | 🟢 合理（调试用） |
| `GET /documents/*/chunks` | `source_refs` | ❌ 不展示 | 🟢 合理（详情模态框用） |

> **结论：响应字段没有真正的冗余。** 前端不展示的字段要么是后端自用、要么是调试/溯源用途、要么是详情模态框中才会展开使用。没有需要删除的字段。

---

## 六、汇总结论

### 6.1 严重问题（必须修复）

| # | 问题 | 修复方案 |
|----|------|----------|
| 1 | `POST /ingest` 缺少 `source_hash` | 前端 `documents.js:312` 从 upload 响应中取 `result.source_hash` 传入 |
| 2 | 手动入库无法获取 `source_hash` | 手动入库模态框应改为先上传文件再入库，或要求输入 hash |
| 3 | `finished_at` ↔ `completed_at` 不匹配 | 统一为一个字段名，建议后端改为 `completed_at` 或前端改为 `finished_at` |

### 6.2 接口质量评分

| 端点 | 请求正确性 | 响应正确性 | 前端消费率 | 评分 |
|------|-----------|-----------|-----------|------|
| `GET /health` | ✅ | ⚠️ 信息不足 | 50% | B |
| `POST /upload` | ✅ | ✅ | 30% | B |
| `POST /ingest` | 🔴 缺必填字段 | ✅ | 60% | **D** |
| `GET /ingest/{job_id}` | ✅ | 🟡 字段名不一致 | 90% | C |
| `POST /search` | ✅ | ✅ | 95% | **A** |
| `GET /documents` | ✅ | ✅ | 60% | B |
| `GET /documents/{doc_id}` | ✅ | ✅ | 70% | A |
| `GET /documents/{doc_id}/elements` | ✅ | ✅ | 30% | A |
| `GET /documents/{doc_id}/chunks` | ✅ | ✅ | 50% | A |

### 6.3 总体评价

- **接口设计**：RESTful 风格一致，请求/响应模型定义清晰
- **前后端对接**：`POST /search` 完美对接；`POST /ingest` 存在阻塞性 bug
- **冗余**：无真正冗余的请求/响应字段
- **缺失**：缺少删除 API、统计 API、健康检查详情、服务端分页
- **关键修复优先级**：P0 两个 → P1 一个 → 其余按需
