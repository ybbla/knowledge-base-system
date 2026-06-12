## 1. 基础设施准备

- [x] 1.1 `docker-compose.yml` 增加 Milvus standalone（v2.5+）、etcd（Milvus 依赖）、MinIO 三个服务，配置健康检查和数据卷
- [x] 1.2 `requirements.txt` 增加 `pymilvus>=2.5.0` 和 `minio>=7.2.0`
- [x] 1.3 `app/core/config.py` 新增 Milvus 配置项（`MILVUS_ENABLED`、`MILVUS_HOST`、`MILVUS_PORT`、`MILVUS_COLLECTION`）和 MinIO 配置项（`MINIO_ENABLED`、`MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MINIO_BUCKET_INPUT`、`MINIO_BUCKET_ASSETS`、`MINIO_SECURE`、`MINIO_PRESIGNED_EXPIRY`）
- [x] 1.4 `app/core/config.py` 新增资源限制配置项（`MAX_ASSET_SIZE_MB=100`、`MAX_ASSETS_PER_DOC=100`），以及检索可调参数显式配置（`VECTOR_TOP_K`、`BM25_TOP_K`、`FUSION_TOP_K`、`RRF_K` 已在阶段 1 定义，确认可用于调优）

## 2. Milvus 向量索引（Dense）

- [x] 2.1 新建 `indexing/milvus_vector.py`：实现 `MilvusVectorIndex(VectorIndex)`，封装 Milvus 连接管理（connect/ensure_collection/disconnect）
- [x] 2.2 实现 Collection schema 自动创建：dense_vector（FloatVector 1024d）+ 元数据字段（chunk_id、doc_id、content、category、knowledge_type、title_path、source_refs、asset_refs、metadata），chunk_id 为主键
- [x] 2.3 实现 `add(chunk_id, vector, metadata)`：向 Milvus insert entity，metadata 中 JSON 字段序列化为 VARCHAR（Milvus JSON 字段可选升级）
- [x] 2.4 实现 `delete(chunk_id)`：按主键删除 entity
- [x] 2.5 实现 `search(query_vector, top_k, category)`：dense vector 检索，`category` 过滤通过 Milvus filter expression 实现
- [x] 2.6 为 dense_vector 字段创建 IVF_FLAT 索引（nlist=128，metric_type=COSINE），nlist 可通过配置调整

## 3. Milvus BM25 索引（Sparse）+ Hybrid Search

- [x] 3.1 新建 `indexing/milvus_sparse.py`：实现 `MilvusSparseIndex(BM25Index)`，封装 jieba 分词 + TF-IDF 稀疏向量编码
- [x] 3.2 实现全局 IDF 字典维护：入库时更新 token DF，按 DF 排序截断（最大词汇量 100000），IDF 字典持久化到 PostgreSQL 表 `idf_stats`（或与 MilvusVectorIndex 共享 Collection 连接管理）
- [x] 3.3 实现 `add(chunk_id, text, metadata)`：jieba 分词 → 查询全局 IDF → 生成 `{token_id: tf*idf}` 稀疏向量 → insert 到 Milvus
- [x] 3.4 实现 `search(query, top_k, category)`：查询文本分词 → 生成稀疏向量 → Milvus sparse vector search
- [x] 3.5 为 sparse_vector 字段创建 SPARSE_INVERTED_INDEX 索引
- [x] 3.6 在 `MilvusVectorIndex` 或新建 `indexing/milvus_hybrid.py` 中实现 Hybrid Search：封装 `hybrid_search(dense_req + sparse_req, RRFRanker(k=60))`
- [x] 3.7 更新 `RetrievalPipeline`：Milvus 可用时走 Hybrid Search；不可用时走现有的双路独立检索 + 应用层 RRF fallback

## 4. MinIO 对象存储

- [x] 4.1 新建 `assets/minio_store.py`：实现 `MinioAssetStore(AssetStore)`，封装 MinIO 客户端连接、Bucket 自动创建（`kb-input`、`kb-assets`）
- [x] 4.2 实现 `put(asset)`：Asset 元数据委托给 PostgreSQL/Memory 存储，关联的文件通过 MinIO SDK `put_object()` 上传
- [x] 4.3 实现 `get(asset_id)`：从元数据存储获取 Asset，动态生成 `storage_uri` 的 presigned GET URL（有效期 `MINIO_PRESIGNED_EXPIRY` 秒）
- [x] 4.4 实现 `delete(asset_id)`：删除 MinIO 文件和元数据记录
- [x] 4.5 实现实用函数 `parse_minio_uri(uri: str)` 和 `make_minio_key(doc_id, file_name)`：统一 MinIO 路径格式

## 5. 上传 API 适配 MinIO

- [x] 5.1 修改 `app/api/upload.py`：MinIO 启用时文件流写入 `kb-input` Bucket（路径 `{doc_id[:2]}/{doc_id}/{file_name}`），`source_uri` 返回 `minio://kb-input/...`；MinIO 未启用时回退现有本地磁盘写入
- [x] 5.2 修改 `ingestion/pipeline.py` 中的文件读取：支持解析 `minio://` URI，通过 MinIO SDK `get_object()` 获取文件流

## 6. 图片处理链路

- [x] 6.1 新建 `assets/image_processor.py`：实现 `process_image(asset)` — 读取图片字节（远程下载或本地文件）→ 校验魔数 → 检查大小 → 计算 `content_hash`
- [x] 6.2 实现 hash 去重逻辑：查询已有 Asset（`content_hash` + `status=ready`），命中则复用 `storage_uri`，未命中则上传 MinIO 并创建新 Asset
- [x] 6.3 修改 `ingestion/pipeline.py` 中入库流程：解析器生成 Asset 后 → 调用 `image_processor.process_image()` → 更新 Asset 状态 → 关联到知识块 `asset_refs`
- [x] 6.4 处理失败路径：下载超时/校验失败/上传失败 → Asset `status=failed` + `error_message`，不阻塞其他元素

## 7. 视频链接资源化

- [x] 7.1 修改 `parsers/markdown_parser.py` 和 `parsers/docx_parser.py`：识别视频链接（`<video>` 标签、Markdown 视频语法、YouTube/Vimeo URL 模式），创建 `ParsedElement(element_type=video)` 或合并到现有元素
- [x] 7.2 修改 `ingestion/pipeline.py`：视频元素创建 Asset（`asset_type=video`，`status=pending`，`original_uri`=链接，`storage_uri=null`，`extracted_text=null`），不执行下载
- [x] 7.3 视频 Asset 关联到知识块 `asset_refs`（`relation=demonstration` 或 `illustration`）

## 8. 资源数量限制

- [x] 8.1 修改 `ingestion/pipeline.py`：入库前统计单文档资源总数，超过 `MAX_ASSETS_PER_DOC` 时超出的 Asset 标记 `status=skipped`
- [x] 8.2 修改 `assets/image_processor.py`：图片大小超过 `MAX_ASSET_SIZE_MB` 时标记 `status=skipped`，记录 `max_asset_size_exceeded`

## 9. 依赖注入与后端切换

- [x] 9.1 修改 `app/core/deps.py`：根据 `MILVUS_ENABLED` 选择 `MilvusVectorIndex`/`MemoryVectorIndex` 和 `MilvusSparseIndex`/`MemoryBM25Index`；根据 `MINIO_ENABLED` 选择 `MinioAssetStore`/（PG 或 Memory）；Milvus 连接管理和优雅关闭（FastAPI lifespan）
- [x] 9.2 修改 `app/main.py`：应用启动时初始化 Milvus Connection + Collection，关闭时 disconnect；MinIO Bucket 检查和创建
- [x] 9.3 确保 `BACKEND=memory` + 默认配置（Milvus/MinIO 均禁用）时所有现有功能不变

## 10. 检索结果资源 URL

- [x] 10.1 修改 `retrieval/pipeline.py` 中 `asset_refs` 的 resolve 逻辑：当 Asset 的 `storage_uri` 为 `minio://` 前缀时动态生成 presigned URL；外部 URL 直接透传；null 则保留 null
- [x] 10.2 确保 `SearchResultItem.asset_refs[].storage_uri` 返回可直接渲染的 HTTP URL

## 11. 评测驱动参数调优

- [x] 11.1 确认现有配置项（`VECTOR_TOP_K`、`BM25_TOP_K`、`FUSION_TOP_K`、`RRF_K`）已通过 pydantic-settings 自动从环境变量读取，评估是否需要热加载支持（当前启动时读取一次），若需要则引入 `@lru_cache` 或配置中心
- [x] 11.2 编写 `tests/evaluation/tune_params.py`（或扩展现有评测脚本）：支持参数网格搜索，自动记录不同参数组合的 Recall@5 和 MRR，输出最优参数

## 12. 测试与集成验证

- [x] 12.1 编写 `tests/test_milvus_indexing.py`：MilvusVectorIndex 和 MilvusSparseIndex 的 add/search/delete 操作（需要 Docker Milvus）
- [x] 12.2 编写 `tests/test_minio_storage.py`：MinioAssetStore 的 put/get/delete、presigned URL 生成（需要 Docker MinIO）
- [x] 12.3 编写 `tests/test_asset_processing.py`：图片下载/校验/hash 去重/上传/失败降级
- [x] 12.4 编写 `tests/test_ingestion_with_milvus_minio.py`：入库端到端（Markdown + DOCX → 解析 → LLM 语义提取 → Milvus 索引 + MinIO 资产）
- [x] 12.5 编写 `tests/test_search_with_milvus.py`：检索端到端（查询重写 → Milvus Hybrid Search → 重排 → SearchResult 含 presigned URL）
- [x] 12.6 运行全量回归测试：`BACKEND=memory` + 默认配置，确认所有 30+ 现有测试保持通过
- [x] 12.7 启动完整 Docker 环境（PG+Milvus+etcd+MinIO），运行端到端烟雾测试，验证完整链路
