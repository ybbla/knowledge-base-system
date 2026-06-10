## 1. 数据模型对齐

- [x] 1.1 Document 模型新增 `category: str = "通用"` 字段
- [x] 1.2 KnowledgeChunk 模型新增 `category: str = "通用"` 字段
- [x] 1.3 SearchResultItem 模型新增 `category: str` 和 `knowledge_type: KnowledgeType` 顶层字段

## 2. 文件上传 API

- [x] 2.1 新建 `app/api/upload.py`，实现 `POST /upload` multipart/form-data 端点
- [x] 2.2 文件写入 `data/uploads/`，生成 `file://` 格式的 `source_uri` 和 sha256 `source_hash`
- [x] 2.3 自动创建 `data/uploads/` 目录
- [x] 2.4 支持可选 `title`、`category` 字段（未指定默认取文件名和 `"通用"`）

## 3. 入库 API 与流程变更

- [x] 3.1 `IngestDocument` 请求模型：移除 `content` 字段，`source_uri` 改为必填，新增 `category: str = "通用"`
- [x] 3.2 `/ingest` 响应状态码改为 202
- [x] 3.3 `ingestion/pipeline.py`：从 Document 读取 `category` 传递给 KnowledgeChunk
- [x] 3.4 从 `data/uploads/` 的 `source_uri` 读取文件内容（`file://` scheme 解析）

## 4. 索引层变更

- [x] 4.1 `indexing/memory_vector.py`：索引元数据新增 `category`，支持后置 `category` 过滤
- [x] 4.2 `indexing/memory_bm25.py`：支持 `category` 过滤
- [x] 4.3 `indexing/base.py`：抽象接口更新 `category` 过滤参数签名

## 5. 检索链路变更

- [x] 5.1 `app/api/search.py`：`filters` 支持 `category`（移除 `knowledge_domain`）
- [x] 5.2 `retrieval/pipeline.py`：组装 SearchResultItem 时填充 `category` 和 `knowledge_type` 顶层字段
- [x] 5.3 检索 pipeline 传递 `category` 过滤到双路索引调用

## 6. 测试适配

- [x] 6.1 更新现有单元测试，适配模型字段和 API 签名变更
- [x] 6.2 新增 `/upload` 端点测试（上传文件、无 title、无 category）
- [x] 6.3 新增 `/ingest` 端点测试（source_uri 必填、category 默认值）
- [x] 6.4 新增 `/search` 按 `category` 过滤的端到端测试
- [x] 6.5 运行全量测试确保所有通过
