## Context

阶段 2 将 Document/ParsedElement/Asset/KnowledgeChunk 元数据持久化到 PostgreSQL，但向量索引（numpy cosine）和 BM25 索引（jieba + rank_bm25）仍存于进程内存。服务重启后索引全部丢失，需重新 embedding 全部知识块才能恢复检索。上传文件写本地磁盘，Asset 的 `storage_uri` 为空。

阶段 3 引入 Milvus（向量 + BM25 持久化索引）和 MinIO（对象存储），使检索索引和文件资源在服务重启后完整保留。

**约束**：
- `BACKEND=memory` 模式零依赖可运行，所有现有测试保持通过
- Milvus standalone 和 MinIO 均通过 Docker Compose 部署
- 火山引擎 API 为唯一 LLM/Embedding 服务
- 索引接口基类 `VectorIndex` / `BM25Index` 已定义，新实现需匹配

## Goals / Non-Goals

**Goals:**
- 向量索引和 BM25 索引持久化到 Milvus，服务重启秒级恢复
- 文件上传从本地磁盘切换到 MinIO 对象存储
- 入库时图片资源自动下载→去重→上传 MinIO，生成 `storage_uri`
- 检索结果中的 `asset_refs` 包含 MinIO presigned URL
- 视频链接在入库时自动创建 Asset 记录
- Asset `content_hash` 在入库时进行去重检查
- 混合检索参数可配置化，支持评测驱动调优
- Milvus 和 MinIO 均为可选——未配置时回退到现有内存/本地磁盘实现

**Non-Goals:**
- 图片/视频多模态内容理解（阶段 5）
- 其他文档格式解析（阶段 4：PDF/HTML/XLSX/PPTX）
- BM25 独立部署（Elasticsearch/OpenSearch）
- Milvus 集群模式部署（仅 standalone）
- MinIO 分布式模式部署（仅单节点）
- 数据库迁移工具（Alembic）引入

## Decisions

### 1. Milvus Collection 设计：单 Collection 双向量字段

**选择**：一个 Collection 同时容纳 dense vector（1024d）和 sparse vector（BM25），通过 Milvus Hybrid Search API 融合。

```
Collection: knowledge_chunks
├── chunk_id (VarChar, primary key)
├── doc_id (VarChar)
├── content (VarChar, max 65535)
├── dense_vector (FloatVector, 1024d)     ← 火山 Embedding
├── sparse_vector (SparseFloatVector)     ← jieba + TF-IDF 编码
├── category (VarChar)
├── knowledge_type (VarChar)
├── title_path (JSON)
├── source_refs (JSON)
├── asset_refs (JSON)
├── metadata (JSON)
└── created_at (Int64)
```

索引策略：
- `dense_vector`: IVF_FLAT（nlist=128），`metric_type=COSINE`——与当前 MemoryVectorIndex 的余弦相似度行为一致，避免向量是否归一化的隐式依赖；若火山 Embedding 输出已 L2 归一化则 COSINE 等价于 IP
- `sparse_vector`: SPARSE_INVERTED_INDEX

**备选方案**：
- *两个独立 Collection*（vector 和 bm25 分开）：增加应用层融合复杂度，Milvus Hybrid Search 无法使用。
- *Milvus 内置 BM25 Function*：依赖 Milvus analyzer 中文分词，效果未知且不可控；jieba 的分词质量已在阶段 1-2 验证。

**为什么 jieba_fast 分词 + 自编码稀疏向量**：保留 jieba 中文分词的可控性（jieba_fast 是 jieba 的 C++ 重写，API 和词典完全兼容，速度 2-3 倍），同时利用 Milvus 持久化存储和 Hybrid Search 原生融合。TF-IDF 编码逻辑简单，不依赖外部模型。

### 2. BM25 稀疏向量编码

**选择**：应用层用 jieba_fast（jieba 的 C++ 高性能重写，API 完全兼容）分词 + TF-IDF 权重生成稀疏向量，存入 Milvus `SPARSE_FLOAT_VECTOR` 字段。

```python
# 伪代码
tokens = jieba.lcut(text)
tf = Counter(tokens)
idf = corpus_idf  # 在入库时维护全局 IDF
sparse_vector = {token_to_id[t]: tf[t] * idf[t] for t in tf}
```

Milvus Hybrid Search 使用 `RRFRanker` 融合 dense 和 sparse 两路分数。`RRFRanker(k=60)` 与应用层阶段 2 的 RRF 逻辑一致。

**备选方案**：
- *Milvus 内置 BM25 Function + zh analyzer*：免去应用层编码，但中文分词效果未经验证。
- *保留 MemoryBM25Index 不变*：BM25 不持久化，重启仍需重建，阶段 3 只解决一半问题。

**选择理由**：jieba_fast 分词质量可控（与 jieba 词典兼容，速度 2-3 倍），全局 IDF 维护开销小，Milvus Hybrid Search 原生融合比应用层 RRF 少一次网络往返。

### 3. 混合检索融合位置

**选择**：默认使用 Milvus Hybrid Search（`hybrid_search()` + `RRFRanker`），应用层 RRF 作为 fallback。

```text
正常路径：
  query → rewrite → embedding → Milvus.hybrid_search(dense + sparse, RRFRanker)
  → Milvus 内部完成双路检索+融合 → 返回 top_k

Fallback 路径（Milvus 不可用时）：
  query → rewrite → embedding → Milvus.search(dense) + Milvus.search(sparse)
  → 应用层 RRF 融合 → 返回 top_k
```

`hybrid_search()` 返回的分数已融合，直接作为 `score`；`score_components` 需额外查询单路分数。

**备选方案**：
- *始终应用层 RRF*：简单但多一次数据往返，且无法利用 Milvus 的 `hybrid_search` 性能优化。
- *始终 Milvus Hybrid Search*：单一依赖，Milvus 不可用时检索完全失败。

**选择理由**：Milvus Hybrid Search 是性能更优的正常路径，应用层 RRF fallback 保证可用性。

### 4. MinIO Bucket 结构

**选择**：两个 Bucket，按 `doc_id` 前两位分片。

```
kb-input/          ← 用户上传的原始文档
  {doc_id[:2]}/{doc_id}/{file_name}

kb-assets/         ← 图片、视频、附件等资源
  {doc_id[:2]}/{doc_id}/{asset_id}/{file_name}
```

分片策略防止单目录文件过多，参考 MinIO 官方最佳实践。

上传后返回 `minio://kb-input/{doc_id[:2]}/{doc_id}/{file_name}` 作为 `source_uri`。

**备选方案**：
- *单 Bucket 按前缀区分*：管理简单但权限粒度粗，后续无法对 input 和 assets 设置不同生命周期策略。
- *不分片*：小规模可行，但生产规模下单目录文件数爆炸。

### 5. 后端切换策略

**选择**：新增配置项 `MILVUS_ENABLED` 和 `MINIO_ENABLED`（默认 `false`），与 `BACKEND` 解耦。

```python
# deps.py 逻辑
if settings.milvus_enabled:
    vector_index = MilvusVectorIndex()
    bm25_index = MilvusSparseIndex()
else:
    vector_index = MemoryVectorIndex()
    bm25_index = MemoryBM25Index()

if settings.minio_enabled:
    asset_store = MinioAssetStore()
elif settings.backend == "postgres":
    asset_store = PgAssetStore(session_factory)
else:
    asset_store = MemoryAssetStore()
```

**为什么与 BACKEND 解耦**：允许 `BACKEND=memory + MinIO`（纯内存检索但有对象存储）或 `BACKEND=postgres + memory-index`（PG 持久化但暂不用 Milvus）等灵活组合，降低迁移风险。

**备选方案**：
- *统一 BACKEND=milvus 模式*：简单但失去灵活组合能力，出问题时回退粒度太粗。
- *Milvus 始终启用*：与向后兼容约束冲突，开发阶段不应强制依赖 Docker。

### 6. 图片处理链路

**选择**：入库管道中新增 `image_processor` 模块，处理 DOCX/Markdown 解析出的图片 Asset。

```text
解析器提取图片
  → 计算 content_hash (sha256)
  → 查询是否已有相同 hash 的 Asset（去重）
  → 已有：复用 storage_uri，更新 source_element_id
  → 无：
      → 下载图片（如为远程 URL）
      → 校验大小（< max_asset_size）
      → 上传到 MinIO kb-assets
      → 更新 Asset.status=ready, storage_uri=minio://...
  → 返回 Asset
```

限制：单资源最大 100MB（开发文档 §2.4），单文档最多 100 个资源。

**image_processor 与 MinioAssetStore 的接口约定**：`image_processor` 负责下载和校验，产出处理后的图片字节 + `content_hash`；`MinioAssetStore` 负责上传和元数据存储。为了不破坏 `AssetStore` ABC 现有接口（`put(asset: Asset)`），MinioAssetStore 在 `put()` 内部自行从 `asset.original_uri` 读取/下载文件——这意味着 MinioAssetStore 复用 image_processor 的下载校验逻辑，或接收一个可选的 `data: bytes | None` 参数。具体实现时，若 Pipeline 中先调用 image_processor 再生产 Asset，则 Asset 对象上附加临时 `_data` 属性供 MinioAssetStore 直接使用，避免重复下载。

**备选方案**：
- *入库时不下载，仅记录 URL*：简单但 URL 可能过期，后续检索时无法渲染。
- *同步阻塞下载*：简单但大文件会阻塞入库管道。

**选择理由**：阶段 3 采用同步下载（图片通常 < 10MB），后续阶段可改为异步队列处理大文件和视频。

### 7. 视频资源化

**选择**：解析器识别视频链接后，立即创建 Asset（`asset_type=video`，`status=pending`），但阶段 3 不做下载和语义提取。

```
识别视频链接 → 创建 Asset(status=pending, storage_uri=null, extracted_text=null)
  → 关联到知识块 asset_refs
  → 阶段 5 异步处理：下载→多模态理解→更新 extracted_text→更新知识块
```

视频语义总结由多模态模型直接生成（开发文档 §5.5），阶段 3 仅完成资源化，不进入多模态链路。

### 8. 配置项设计

```bash
# ── Milvus ──
MILVUS_ENABLED=false           # 是否启用 Milvus
MILVUS_HOST=localhost          # Milvus standalone 地址
MILVUS_PORT=19530
MILVUS_COLLECTION=knowledge_chunks

# ── MinIO ──
MINIO_ENABLED=false            # 是否启用 MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_INPUT=kb-input    # 原始文档 bucket
MINIO_BUCKET_ASSETS=kb-assets  # 资源 bucket
MINIO_SECURE=false             # 阶段 3 不使用 TLS
MINIO_PRESIGNED_EXPIRY=3600    # presigned URL 有效期（秒）

# ── 资源处理 ──
MAX_ASSET_SIZE_MB=100          # 单资源最大大小
MAX_ASSETS_PER_DOC=100         # 单文档最多资源数
```

## Risks / Trade-offs

- **[Milvus 内存占用高]** → Milvus standalone 默认需要 ~4GB 内存，开发机可能不足。Mitigation: 使用 `MILVUS_ENABLED=false` 默认关闭，仅需 Milvus 时手动开启 Docker 服务。
- **[jieba_fast + TF-IDF 稀疏向量维度爆炸]** → 随着入库文档增多，全局词汇表持续增长，稀疏向量维度膨胀。Mitigation: 设置最大词汇量上限（如 100000），超出时按 DF 剪枝；阶段 3 规模不会触及。
- **[Hybrid Search RRFRanker 参数不同]** → Milvus `RRFRanker(k=60)` 与应用层 RRF 行为可能不完全一致。Mitigation: fallback 路径保留应用层 RRF；通过评测集对比两种路径的 Recall@5。
- **[MinIO presigned URL 过期]** → 默认 1 小时有效期，超过后图片不可访问。Mitigation: 检索 API 调用时动态生成 URL（不缓存），前端即取即用；后续可加 CDN。
- **[远程图片下载失败]** → 外部 URL 可能不可达、超时或返回非图片内容。Mitigation: 下载超时设 10s，失败时 Asset 标记 `status=failed` 并记录 `error_message`，不阻塞整体入库。
- **[docker-compose 服务数量增加]** → 从 1 个（PG）增到 4 个（PG+etcd+Milvus+MinIO），本地资源占用和启动时间增加。Mitigation: 开发模式下全部可选，默认不启动；docker-compose profile 分离核心和可选服务。

## Open Questions

1. **Milvus IVF_FLAT nlist 参数**：默认 128，是否需要根据知识库规模（预计 < 10w 条）调小到 64？
2. **全局 IDF 维护**：存储在 Milvus 单独 collection、PG 表，还是内存中每次全量计算？倾向 PG 表（可持久化 + 更新方便）。
3. **Milvus 中文分词**：当前确定使用 jieba_fast 自编码方案。若后续评估阶段发现 Tantivy `chinese_jieba` tokenizer（Rust jieba 移植）效果可接受，可考虑切换以减少应用层编码维护成本。保留再评估的可能性。
4. **presigned URL 有效期**：1 小时是否合适？前端是否需要更长的缓存时间？
