---
name: semantic-chunk-dedup-plan
description: 知识块语义去重升级方案，从精确哈希匹配升级到语义级别去重
metadata:
  type: project
  status: planning
---

## 现状

当前知识块去重仅靠 **SHA-256 精确内容哈希**（`content_hash` 字段），位于以下位置：

- `app/core/models.py:183-186` — `KnowledgeChunk._set_content_hash()` 自动计算哈希
- `app/db/repositories/chunks.py:366` — `find_by_content_hash()` 按哈希查重
- `app/api/v1/chunks.py:219-226` — 创建时哈希去重，409 冲突
- `app/api/v1/chunks.py:348-354` — 更新时哈希去重，409 冲突

## 问题

精确哈希只能检测**逐字相同**的内容，无法识别：

| 场景 | 示例 |
|------|------|
| 同义改写 | "用户需先登录" vs "使用者必须完成登录操作" |
| 详略不同 | 同一事实的简版和详细版 |
| 翻译/别名 | "手机号" vs "电话号码" vs "phone number" |
| 分段重叠 | 同一段原文被不同文档引用，产生多个等价知识块 |

随着多文档入库量增大，知识库会积累大量语义重复的知识块，导致搜索结果冗余、RAG 上下文浪费。

## 核心思路：先哈希，后语义

不改动现有 SHA-256 哈希去重逻辑，在它之后追加一层语义去重，形成两级防线：

```
新知识块
    │
    ▼
┌─────────────────┐
│ 第一层：哈希去重  │  现有逻辑，不动
│ SHA-256 逐字匹配 │  命中 → 409 硬拒绝
└────────┬────────┘
         │ 未命中（哈希不同但语义可能相同）
         ▼
┌─────────────────┐
│ 第二层：语义去重  │  新增逻辑
│ Embedding 相似度 │  命中 → 合并 / 关联 / 提醒
└────────┬────────┘
         │ 也未命中
         ▼
      正常入库
```

---

## 具体设计

### 第一层：哈希去重（不动）

现有 `content_hash` + `find_by_content_hash()` 保持不变，逐字相同直接返回 409。

位置：
- `app/core/models.py:183-186` — `_set_content_hash()`
- `app/db/repositories/chunks.py:366` — `find_by_content_hash()`
- `app/api/v1/chunks.py:219-226` — 创建时去重
- `app/api/v1/chunks.py:348-354` — 更新时去重

### 第二层：语义去重（新增）

哈希不同的情况下，对**当前文档内**的知识块做 Embedding 相似度比对：

```
同一文档的知识块列表
    │
    ▼
embed_text([c.content for c in chunks])   ← 复用入库时已有的 embedding 结果
    │
    ▼
计算 pairwise 余弦相似度矩阵（仅 co正在入库的文档范围内）
    │
    ▼
相似度 > 0.92 的候选对 → 视为语义重复
```

**为什么先限定在同文档内**：跨文档全量比对的计算量随总知识块数 O(N²) 增长；先在同文档内做，后续再按需扩展跨文档。

**复用 Embedding 结果**：入库流程本来就要 embed 所有知识块（`_index_chunks` 调用 `embedding_client.embed_text`），去重步骤插入在 embed 之后、写 Milvus 之前，零额外 Embedding 调用。

### 去重策略（按场景）

| 场景 | 判定方式 | 处理 |
|------|---------|------|
| SHA-256 相同 | 哈希命中 | **硬拒绝** 409（现有逻辑，不改） |
| 哈希不同 + Embedding ≥ 0.95 | 高度语义重复 | **合并**：保留内容更长的那条，短的软删除，记录 `merged_into` |
| 哈希不同 + 0.88 ≤ Embedding < 0.95 | 疑似语义重复 | **标记**：两条都保留，记录 `related_chunk_ids` 互引，搜索时展示关联 |
| 手工 vs 自动 | 任一级别命中 | **手工优先**：手工创建的永远保留，自动抽取的被合并 |
| Embedding < 0.88 | 语义不重复 | 正常入库 |

### 数据模型变更

```python
# KnowledgeChunk 新增字段
class KnowledgeChunk(BaseModel):
    # ... 现有字段保持不变 ...
    merged_into: str | None = None          # 被合并到的目标 chunk_id
    related_chunk_ids: list[str] = []       # 语义相关的其他 chunk
```

- `merged_into`：被合并后指向目标知识块，搜索和列表查询过滤掉 `merged_into IS NOT NULL` 的记录
- `related_chunk_ids`：双向关联，搜索结果中可展开显示关联条目

### DB 迁移

```sql
ALTER TABLE knowledge_chunks ADD COLUMN merged_into VARCHAR(64);
ALTER TABLE knowledge_chunks ADD COLUMN related_chunk_ids JSONB DEFAULT '[]';
CREATE INDEX idx_chunks_merged_into ON knowledge_chunks(merged_into);
```

### 入库存量处理

对已有知识库，提供一次性全量扫描命令：

```bash
python -m knowledge_base_system.scripts.dedup_scan --dry-run   # 预览重复
python -m knowledge_base_system.scripts.dedup_scan --apply      # 执行合并
```

### 配置项

```python
# app/core/config.py 新增
dedup_similarity_merge: float = 0.95    # ≥ 此值自动合并
dedup_similarity_flag: float = 0.88     # ≥ 此值标记关联，< 此值视为不重复
dedup_enabled: bool = True              # 总开关
```

---

## 改动范围

| 文件 | 改动 |
|------|------|
| `app/core/config.py` | 新增 3 个去重配置项 |
| `app/core/models.py` | `KnowledgeChunk` 新增 `merged_into`、`related_chunk_ids` |
| `app/db/models.py` | `DbKnowledgeChunk` 新增对应列 |
| `app/db/repositories/chunks.py` | 新增 `find_semantic_similar(chunk_id, threshold)` |
| `ingestion/pipeline.py` | 在 `_index_chunks` 前插入 `_dedup_chunks(embeddings, chunks)` |
| `app/api/v1/chunks.py` | 创建/更新时的语义去重检查（调 `find_semantic_similar`） |
| `app/api/v1/search.py` | 搜索结果过滤 `merged_into IS NOT NULL` 的记录 |
| `frontend/js/components/chunks.js` | 详情抽屉展示关联关系 |
| `frontend/js/components/search.js` | 结果卡片展示"有重复项"折叠提示 |

### 实施步骤

1. **模型 + DB 迁移**：新增字段、配置项、索引
2. **入库去重**：`_dedup_chunks()` 逻辑，同文档内 Embedding 比对 + 合并
3. **API 适配**：创建/更新/搜索接口适配新字段
4. **存量扫描脚本**：一键处理已有重复
5. **前端适配**：关联关系展示、重复折叠

## 相关文件

- `knowledge_base_system/app/core/models.py` — KnowledgeChunk 模型
- `knowledge_base_system/app/core/config.py` — 阈值配置
- `knowledge_base_system/ingestion/pipeline.py` — 入库主流程
- `knowledge_base_system/app/db/repositories/chunks.py` — 知识块持久化
- `knowledge_base_system/app/api/v1/chunks.py` — 知识块 CRUD API
- `knowledge_base_system/llm/volcengine_client.py` — Embedding 客户端
- `frontend/js/components/chunks.js` — 前端知识块管理
- `frontend/js/components/search.js` — 前端搜索结果
