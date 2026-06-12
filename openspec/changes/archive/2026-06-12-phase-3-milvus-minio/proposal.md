## Why

阶段 2 已将 Document/ParsedElement/Asset/KnowledgeChunk 元数据持久化到 PostgreSQL，但向量索引和 BM25 索引仍存于进程内存——服务重启后索引全部丢失，需要重新 embedding 全部知识块才能恢复检索能力。同时，上传文件写本地磁盘、Asset 无对象存储后端，无法支撑多实例部署和资源的外部访问。阶段 3 解决这两个核心基础设施缺口，使系统向生产可用迈出关键一步。

## What Changes

- 新增 Milvus 向量索引实现，替换内存 numpy cosine 检索，索引数据持久化，重启秒级恢复
- 新增 Milvus BM25 索引实现，替换内存 jieba + rank_bm25 检索，保留 jieba_fast 分词并通过 TF-IDF 编码稀疏向量存入 Milvus，利用 Hybrid Search 原生融合
- 新增 MinIO 对象存储实现，替换本地磁盘写入，支持图片上传、下载和 presigned URL 生成
- Docker Compose 增加 Milvus standalone 和 MinIO 服务
- `/upload` 端点文件写入目标从本地磁盘切换到 MinIO
- 入库链路增加图片下载→hash 去重→MinIO 上传处理
- 视频链接识别后自动创建 Asset 资源记录
- 检索结果中的 `asset_refs` 返回 MinIO presigned URL，前端可直接渲染
- 混合检索参数（RRF k 值、各阶段 top_k）可配置化，支撑评测驱动调优
- 内存索引实现保留为 `BACKEND=memory` 开发模式，Milvus/MinIO 在 `BACKEND=postgres` 模式下可选启用

## Capabilities

### New Capabilities

- `milvus-indexing`: Milvus 部署与连接管理，Collection schema 设计与自动创建，向量索引和 BM25 稀疏向量索引（jieba_fast 分词 + TF-IDF 编码），Hybrid Search 双路融合检索，索引 CRUD 操作
- `minio-storage`: MinIO 部署与连接管理，Bucket 自动创建，文件上传/下载/删除，presigned URL 生成，与 AssetStore 抽象接口对接
- `asset-lifecycle`: 入库时图片资源的下载→content_hash 计算→去重检查→MinIO 上传完整链路，视频链接自动创建 Asset 记录（`status=pending`，语义提取留待阶段 5），Asset 状态流转（`pending`→`ready`/`failed`/`skipped`）

### Modified Capabilities

- `embedding-indexing`: 索引存储后端从"内存"变更为"Milvus（默认）或内存（开发模式）"；向量检索和 BM25 检索的接口契约不变，实现替换
- `hybrid-retrieval`: 双路检索融合位置从应用层 RRF 变更为 Milvus Hybrid Search 原生融合（可选保留应用层 RRF 作为 fallback）；检索参数（RRF k、各阶段 top_k）改为可配置
- `file-upload`: 文件写入目标从本地磁盘（`file://data/uploads/`）变更为 MinIO（`minio://kb-input/`）；响应中 `source_uri` 格式相应变更

## Impact

- **新增依赖**: `pymilvus`（Milvus Python SDK）、`minio`（MinIO Python SDK）
- **基础设施**: `docker-compose.yml` 增加 `milvus-standalone`、`etcd`、`minio` 三个服务
- **新增模块**: `indexing/milvus_vector.py`、`indexing/milvus_hybrid.py`、`assets/minio_store.py`、`assets/image_processor.py`
- **修改模块**: `app/core/config.py`（新增 MILVUS_*/MINIO_* 配置项）、`app/core/deps.py`（新增 Milvus/MinIO 实例创建与注入）、`app/api/upload.py`（MinIO 写入）、`ingestion/pipeline.py`（图片处理链路）、`retrieval/pipeline.py`（Milvus Hybrid Search 适配）
- **测试**: 新增 Milvus 索引、MinIO 存储、资产去重的单元测试和集成测试
- **向后兼容**: `BACKEND=memory` 模式完全不受影响，所有现有测试保持通过
