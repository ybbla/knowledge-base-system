# 一级标题 — 系统架构概述

系统采用**微服务架构**，核心组件包括 API 网关、消息队列和分布式存储。各服务通过 gRPC 通信，使用`Protobuf`定义接口协议。更多设计细节可参考[架构设计文档](https://example.com/docs/architecture.pdf)和[官方技术博客](https://example.com/blog/arch-overview)。

![系统架构图](https://example.com/diagrams/architecture.png)

## 二级标题 — 核心模块说明

### API 网关模块

API 网关负责请求路由、认证鉴权和限流熔断。主要技术栈：

- 基于 **Nginx + Lua** 的动态路由
- JWT 令牌验证，支持 [RFC 7519](https://tools.ietf.org/html/rfc7519) 标准
- 令牌桶算法限流，参考 [限流最佳实践](https://example.com/docs/rate-limiting.pdf)
- 内置 Prometheus 指标采集，监控大盘见 [Grafana 面板](https://example.com/monitoring.png)

网关部署拓扑图：![网关拓扑](https://example.com/diagrams/gateway-topology.jpg)

### 消息队列模块

消息队列选用 RabbitMQ，通过[官方管理插件](https://www.rabbitmq.com/management.html)进行运维。消息持久化策略如下：

1. 持久化消息写入磁盘，通过 `delivery_mode=2` 确保不丢失
2. 镜像队列跨节点同步，防止单点故障
3. 死信队列处理消费失败的消息，[重试策略文档](https://example.com/retry.xlsx)中有详细说明
4. 监控告警集成 [Prometheus 插件](https://example.com/plugins/prometheus.zip)

### 分布式存储模块

| 存储类型 | 产品 | 用途 | 参考资料 |
|----------|------|------|----------|
| 对象存储 | MinIO | 文件/图片存储 | [部署指南](https://example.com/minio-guide.pdf) |
| 关系数据库 | PostgreSQL | 元数据管理 | [官方文档](https://www.postgresql.org/docs/) |
| 向量数据库 | Milvus | 语义检索 | [性能测试报告](https://example.com/benchmark.xlsx) |
| 缓存 | Redis | 热点数据缓存 | [配置模板](https://example.com/config.pptx) |

各存储组件的架构关系示意：![存储架构](https://example.com/diagrams/storage-arch.webp)

## 三级标题 — 关键流程

### 数据入库流程

```python
def ingest_document(file_path: str, metadata: dict) -> str:
    """文档入库主流程 — 解析 → 语义抽取 → 索引。"""
    parser = ParserRegistry.get(file_path)
    elements = parser.parse(file_path)

    chunks = SemanticExtractor.extract(elements)
    for chunk in chunks:
        vector = embedding_client.embed(chunk.content)
        milvus.insert(chunk.id, vector, chunk.metadata)

    return f"入库完成，共 {len(chunks)} 个知识块"
```

### 数据检索流程

```sql
-- 混合检索查询计划示例
WITH vector_hits AS (
    SELECT chunk_id, score
    FROM milvus_search('dense_vector', query_embedding, top_k=100)
),
bm25_hits AS (
    SELECT chunk_id, score
    FROM milvus_search('sparse_vector', query_text, top_k=100)
),
fused AS (
    SELECT chunk_id, RRF(vector_hits.score, bm25_hits.score) AS rrf_score
    FROM vector_hits FULL OUTER JOIN bm25_hits USING (chunk_id)
)
SELECT * FROM fused ORDER BY rrf_score DESC LIMIT 20;
```

### 配置文件示例

```yaml
# 系统核心配置
milvus:
  host: localhost
  port: 19530
  collection: knowledge_chunks

llm:
  provider: volcengine
  model: deepseek-v4
  max_tokens: 4096

retrieval:
  vector_top_k: 100
  bm25_top_k: 100
  rrf_k: 60
  final_top_k: 10
```

---

## 附录 — 资源链接汇总

### 文档类资源

- [需求规格说明书 v3.2](https://example.com/specs/requirements.pdf)
- [系统设计文档](https://example.com/specs/design.docx)
- [测试用例清单](https://example.com/specs/test-cases.xlsx)
- [项目计划甘特图](https://example.com/specs/project-plan.pptx)

### 多媒体资源

- 系统演示视频：[入门教程](https://www.youtube.com/watch?v=example-tutorial)
- 架构讲解：[B站视频](https://www.bilibili.com/video/BV1xx411x7xx)
- ![部署流程截图](https://example.com/screenshots/deploy-flow.png)
- 本地录屏文件：[性能压测录屏](https://example.com/videos/load-test.mp4)

### 外部参考链接

- [Python 官方文档](https://docs.python.org/3/)
- [FastAPI 框架](https://fastapi.tiangolo.com/)
- [Milvus 向量数据库](https://milvus.io/docs/)
- [火山引擎 Ark API](https://www.volcengine.com/docs/ark)
