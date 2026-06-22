## Context

4 个旧版 API 文件自 v1 接口上线后标记 deprecated，实际无前端调用。但 `upload.py` 中的 `_hash_upload()` 和 `save_upload_file()` 被 `app/api/v1/documents.py` 直接 import 复用，`DEFAULT_CATEGORY` 也被引用。

约束：v1 接口行为不变；`save_upload_file()` 函数签名不可变（被两处调用）。

## Goals / Non-Goals

**Goals:**
- 迁移 `upload.py` 中被复用的工具函数到独立模块
- 删除 4 个旧版 API 文件及路由注册
- 更新所有 import 引用
- 清理测试中对旧端点的直接调用

**Non-Goals:**
- 不修改 v1 接口行为
- 不修改 `save_upload_file()` / `_hash_upload()` 实现
- 不做 `decouple-content-from-parser` 的改动（那是下一个 change）

## Decisions

### 1. 工具函数迁至 `app/api/upload_utils.py`

```
app/api/upload.py  →  删除
    ├─ _hash_upload()        →  app/api/upload_utils.py
    ├─ save_upload_file()    →  app/api/upload_utils.py
    ├─ DEFAULT_CATEGORY      →  app/api/upload_utils.py
    ├─ CHUNK_SIZE            →  app/api/upload_utils.py
    ├─ MINIO_PART_SIZE       →  app/api/upload_utils.py
    └─ router / upload_file  →  删除
```

### 2. 测试处理策略

| 测试文件 | 旧端点调用 | 处理 |
|---------|-----------|------|
| `test_document_dedup.py` | `POST /upload`、`POST /ingest` | 改写为 v1 接口调用，或删除（如果已有等效 v1 测试） |
| `test_search_pipeline.py` | `POST /upload`、`POST /ingest`、`POST /search` | 同上 |
| `test_documents_api.py:936-965` | `POST /upload`、`POST /ingest`、`GET /ingest/{id}` | 这些是显式的向后兼容测试，直接删除 |

### 3. 旧版 documents.py 和 search.py

这两个文件无任何代码被复用，直接删除。

## Risks / Trade-offs

- **[风险] 外部系统仍调旧接口**：→ **缓解**：旧接口标记 deprecated 已超过 2 周，前端已全部迁移至 `/api/v1`；日志中无旧接口调用记录
