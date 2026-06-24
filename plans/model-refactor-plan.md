# 模型与数据库字段重构计划

## 概述

对 `app/core/models.py` 中的领域模型和 `app/db/models.py` 中的 ORM 模型进行一系列修改，同步调整所有调用方。

## 变更清单

### 1. DocStatus 加入 `pending`

**models.py:**
- `DocStatus` 枚举新增 `pending = "pending"`

**影响范围：**
- `DocStatus` 枚举定义本身 — 无调用方破坏性变更
- 前端 `dashboard.js` 中 `_formatStatus` 可能需要处理 pending 状态

### 2. AssetStatus 加入 `downloading`

**models.py:**
- `AssetStatus` 枚举新增 `downloading = "downloading"`

**影响范围：**
- `AssetStatus` 枚举定义 — 已有调用方（parsers）只使用 `ready`/`failed`，无破坏性变更

### 3. AssetType 加入 `video`

**models.py:**
- `AssetType` 枚举新增 `video = "video"`

**影响范围：**
- 枚举定义 — 已有调用方使用 `image`/`image_link`/`video_link`/`document_link`，新增 `video` 不冲突

### 4. 去掉 `Render` 类

**models.py:**
- 删除 `Render` 类定义（第 76-78 行）

**影响范围（需同步修改）：**
- `app/core/models.py`: `AssetRef` 去掉 `render` 字段
- `app/db/repositories/chunks.py`: `_from_db` 和 `_to_db` 中不再序列化/反序列化 `render`
- `app/db/repositories/chunks.py`: 移除 `Render` 导入
- 前端：`chunks.js` 中的 `renderChunkMiniMeta` 和详情展示可能使用 `render` — 需确认后调整
- `llm/prompts.py` / `llm/semantic_extractor.py`: 可能生成 `AssetRef` 含 `render` 字段

### 5. AssetRef 去掉 `linked_text`

**models.py:**
- `AssetRef.linked_text` 字段删除

**影响范围（需同步修改）：**
- `app/db/repositories/chunks.py`: `_from_db` / `_to_db` 中不再序列化/反序列化 `linked_text`
- `llm/semantic_extractor.py`: 语义抽取 prompt 中可能输出 `linked_text`
- 前端：chunks 详情展示

### 6. ParsedElement 加入 `created_at`

**models.py:**
- `ParsedElement` 新增 `created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))`

**影响范围（需同步修改）：**
- `app/db/models.py`: `DbParsedElement` 新增 `created_at` 列
- `app/db/repositories/elements.py`: `_to_db` / `_from_db` 传递 `created_at`
- 所有构造 `ParsedElement` 的地方 — 解析器（markdown/html/pdf/pptx/xlsx/docx parser）— 使用默认值，无需修改

### 7. Asset 去掉 `updated_at`

**models.py:**
- `Asset` 删除 `updated_at` 字段

**影响范围（需同步修改）：**
- `app/db/models.py`: `DbAsset` 删除 `updated_at` 列
- `app/db/repositories/assets.py`: `_to_db` / `_from_db` 不再传递 `updated_at`

### 8. Asset: `source_element_id` → `element_id`

**models.py:**
- `Asset.source_element_id` 重命名为 `element_id`

**影响范围（需同步修改）：**
- `app/db/models.py`: `DbAsset.source_element_id` → `element_id`
- `app/db/repositories/assets.py`: `_to_db` / `_from_db` 字段名变更
- 所有构造 `Asset` 的地方（parsers、ingestion pipeline）— 字段名变更

### 9. Asset 去掉 `mime_type`

**models.py:**
- `Asset` 删除 `mime_type` 字段

**影响范围（需同步修改）：**
- `app/db/models.py`: `DbAsset` 删除 `mime_type` 列
- `app/db/repositories/assets.py`: `_to_db` / `_from_db` 不再传递 `mime_type`
- `app/assets/minio_store.py`: `put()` 方法中 `upload_bytes` 调用使用了 `asset.mime_type`

### 10. Asset 加入存嵌入图片和视频的字段

**models.py:**
- `Asset` 新增 `embedded_data: bytes | None = None`（或类似字段名），用于存储内嵌二进制数据

**影响范围：**
- 解析器中构造 Asset 时传入内嵌数据
- `app/assets/minio_store.py`: 使用该字段替代现有的 `_data` 临时属性

### 11. Asset 加入文档版本 `doc_version`

**models.py:**
- `Asset` 新增 `doc_version: int = 1`

**影响范围（需同步修改）：**
- `app/db/models.py`: `DbAsset` 新增 `doc_version` 列
- `app/db/repositories/assets.py`: `_to_db` / `_from_db` 传递 `doc_version`
- 所有构造 `Asset` 的地方 — 使用默认值 1，无需修改

### 12. KnowledgeChunk 去掉 `doc_id`

**models.py:**
- `KnowledgeChunk` 删除 `doc_id` 字段

**重要说明：** `source_refs` 中的 `SourceRef` 已经包含 `doc_id`，所以 chunk 级别的 `doc_id` 是冗余的。但这是一个**重大破坏性变更**，影响范围很广。

**影响范围（需同步修改）：**

1. **`app/db/models.py`**: `DbKnowledgeChunk` 删除 `doc_id` 列和 ForeignKey
2. **`app/db/repositories/chunks.py`**: 
   - `_to_db` / `_from_db` / `put` 不再传递 `doc_id`
   - `list_by_doc_id` — 需要通过 `source_refs` JSONB 查询（`source_refs @> '[{"doc_id": "xxx"}]'`）
   - `bulk_update_status_by_doc_id` — 同上
   - `bulk_update_fields_by_doc_id` — 同上
   - `list_paginated` — `doc_id` 过滤需改为 JSONB 查询；`source_type` 过滤需要 JOIN 方式调整
   - `count_by_doc_id` — 同上
3. **`app/api/v1/chunks.py`**:
   - `_chunk_to_list_item` — 通过 `source_refs[0].doc_id` 获取文档标题
   - `_chunk_to_detail` — 同上
   - `create_chunk` — 不再传 `doc_id` 给 `KnowledgeChunk` 构造，但可通过 `source_refs` 传入
   - `list_chunks` — `doc_id` 过滤参数仍需支持
4. **`app/api/v1/documents.py`**: 
   - 删除文档时级联更新 chunk 状态 — 需要通过 `source_refs` 查找
   - `touch_updated_at` — 不再需要
5. **`app/api/v1/search.py`**: 搜索结果中可能引用 `doc_id`
6. **`app/api/v1/services.py`**: `reindex_chunk` / `reindex_chunks_by_doc_id`
7. **`indexing/milvus_vector.py`**: 
   - `_build_fields` 中 `doc_id` 来自 metadata
   - `_default_entity` 中 `doc_id` 默认空字符串
   - `_SEARCH_OUTPUT_FIELDS` 中仍有 `doc_id`
8. **`indexing/milvus_bm25.py`**: 类似 milvus_vector 的处理
9. **`ingestion/pipeline.py`**: 构造 `KnowledgeChunk` 时传 `doc_id`
10. **`llm/semantic_extractor.py`**: 语义抽取输出可能包含 `doc_id`
11. **前端**: chunks 列表中显示文档标题，需要通过 `source_refs` 获取

## 执行顺序

按依赖关系排列：

1. **Phase 1 — 枚举和简单字段变更**（无破坏性）
   - DocStatus + pending
   - AssetStatus + downloading
   - AssetType + video
   - ParsedElement + created_at

2. **Phase 2 — Render 删除 + AssetRef 简化**
   - 删除 Render 类
   - AssetRef 去掉 linked_text、render
   - 同步修改 chunks.py repository、LLM prompts、前端

3. **Phase 3 — Asset 模型重构**
   - 去掉 updated_at
   - source_element_id → element_id
   - 去掉 mime_type
   - 加入 embedded_data 字段
   - 加入 doc_version
   - 同步修改 DbAsset、PgAssetStore、minio_store、所有解析器

4. **Phase 4 — KnowledgeChunk 去掉 doc_id**（最大变更）
   - 修改模型和 DB 模型
   - 修改 repository（JSONB 查询替代直接列查询）
   - 修改 API 层
   - 修改索引层
   - 修改 ingestion pipeline
   - 修改 LLM 语义抽取
   - 修改前端

## 风险点

- Phase 4 中 `list_by_doc_id` 改为 JSONB 查询可能有性能影响，需添加 GIN 索引
- `source_refs` 可能包含多个不同 `doc_id` 的引用（跨文档知识块），`doc_id` 语义变为"主要关联文档"
- 前端 chunks 列表的"文档标题"列依赖 `doc_id`，需改为从 `source_refs` 获取
