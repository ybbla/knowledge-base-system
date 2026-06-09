# 测试报告 — implement-mvp-phase-1

**日期:** 2026-06-09
**Python:** 3.12.3
**pytest:** 9.0.3
**平台:** Windows 11

---

## 总览

| 指标 | 数值 |
|------|------|
| 总计 | 26 |
| 通过 | 26 |
| 失败 | 0 |
| 跳过 | 0 |
| 警告 | 1 (Starlette deprecation) |
| 总耗时 | 342.53s (5分42秒) |

> 警告说明：`starlette.testclient` 使用了 `httpx`，建议安装 `httpx2`。该警告不影响功能。

---

## 测试输入数据（解析器演示用）

输入文档：**产品使用手册** — 包含 h1/h2/h3 标题、2 个段落、1 个表格（3 行数据）、1 个列表（2 个项目）、1 个图片链接、1 个外部链接。

| 解析输出 | 数量 |
|----------|------|
| 解析元素（ParsedElement） | 12 |
| 资源（Asset） | 1 |
| 嵌入文档 | 0 |
| 文档哈希 | sha256:1319f869... |

元素分布：标题×3、段落×7、表格×1、列表×1

---

## 各模块测试结果

### test_models.py — 数据模型单元测试 (12/12 通过)

| 测试用例 | 结果 | 验证内容 |
|----------|------|----------|
| test_string_hash | 通过 | SHA-256 哈希格式：`sha256:` + 64 位十六进制字符 |
| test_different_content_different_hash | 通过 | 不同内容生成不同哈希值 |
| test_bytes_hash | 通过 | 字符串和 bytes 输入生成相同哈希 |
| test_prefix | 通过 | ID 前缀格式：`doc_` + 12 位随机十六进制 |
| test_unique | 通过 | 连续生成 100 个 ID 全部唯一 |
| test_defaults | 通过 | Document 默认值：version=1, status=pending |
| test_serialization | 通过 | Pydantic 序列化/反序列化往返一致 |
| test_table_with_structured_data | 通过 | ParsedElement 的结构化数据存储表头 |
| test_asset_refs | 通过 | KnowledgeChunk 的 asset_refs + content_hash 自动计算 |
| test_source_refs | 通过 | KnowledgeChunk 的 source_refs + SourceLocation(page=3) |
| test_empty_result | 通过 | SearchResult 默认值：空结果、total_count=0 |
| test_with_results | 通过 | SearchResult 包含 SearchResultItem、分数正确传递 |

### test_fusion.py — RRF 融合算法单元测试 (4/4 通过)

| 测试用例 | 结果 | 验证内容 |
|----------|------|----------|
| test_basic_fusion | 通过 | 融合两个排序列表，在两者中排名靠前的 b 获得最高融合分 |
| test_single_list | 通过 | 单个列表（另一列表为空）仍正确排序，a 排在 b 前 |
| test_empty | 通过 | 两个空列表 → 空结果 |
| test_disjoint_results | 通过 | 无交集的两个结果集各自被保留，a 和 b 均在结果中 |

### test_markdown_ingest.py — Markdown 解析器单元测试 (7/7 通过)

| 测试用例 | 结果 | 验证内容 |
|----------|------|----------|
| test_supported_types | 通过 | 支持 markdown/md/txt，不支持 pdf |
| test_parse_headings | 通过 | 三级标题正确解析，h1 文本为"产品使用手册" |
| test_parse_table | 通过 | 表格解析为 structured_data，表头 ["状态", "说明"]，含 3 行数据 |
| test_parse_image | 通过 | 图片链接 → Asset，asset_type=image，URI 含 upload-status.png |
| test_parse_list | 通过 | 无序列表含 2 个项目正确解析 |
| test_all_elements_have_sequence_order | 通过 | 所有元素 sequence_order 为正整数且唯一 |
| test_document_hash_set | 通过 | 解析后 source_hash 以 `sha256:` 开头 |

**解析器输入/输出示例：**

输入 Markdown（496 字符）→ 输出：12 个 ParsedElement + 1 个 Asset

元素明细：

| 序号 | 类型 | 文本（截断） |
|------|------|-------------|
| 1 | title (h1) | 产品使用手册 |
| 2 | title (h2) | 上传知识文档 |
| 3 | paragraph | 用户可以在知识库页面上传文档... |
| 4 | paragraph | 上传后系统会显示解析状态： |
| 5 | table | 状态 \| 说明\n处理中 \| ... |
| 6 | title (h3) | 注意事项 |
| 7 | paragraph | 单文件不超过 10 MB |
| 8 | paragraph | 支持批量上传 |
| 9 | paragraph | 界面截图如下： |
| 10 | paragraph | [图片: 上传状态截图] |
| 11 | paragraph | 详细信息请参考 [API 文档] |
| 12 | list (容器) | （内含 2 个子元素） |

### test_search_pipeline.py — 检索管线集成测试 (3/3 通过)

> 依赖火山引擎 ARK API（LLM + Embedding），需网络连接。

**输入文档**（SAMPLE_MARKDOWN）：497 字符，包含标题、段落、表格、列表、图片。

| 测试用例 | 结果 | 验证内容 |
|----------|------|----------|
| test_ingest_completed | 通过 | 录入完成：chunk_count > 0，doc_ids 非空 |
| test_search_returns_results | 通过 | 搜索结果含 search_id/chunk_id/title/content/score/score_components/source_refs/metadata |
| test_search_content_relevant | 通过 | 搜索"上传文档"返回内容包含"上传"和"文档"关键词 |

**检索管线验证的字段：**

- `search_id` — 以 `search_` 开头
- `rewritten_query` — LLM 改写后的查询
- `total_count` — 候选知识块总数
- `results[].chunk_id` — 以 `chunk_` 开头
- `score_components` — 含 vector / bm25 / rerank 三项分维度得分
- `source_refs` — 含 doc_id / element_id 溯源信息
- `metadata.title_path` / `metadata.knowledge_type` — 标题路径和知识类型

---

## 整体流程覆盖

```
POST /ingest
  ├── MarkdownParser.parse()          ← 解析为 ParsedElement + Asset
  ├── RecursiveLoader.load()          ← 递归加载嵌入文档
  ├── SemanticExtractor.extract()     ← LLM 语义提取 → KnowledgeChunk
  ├── EmbeddingClient.embed_text()    ← 向量化
  ├── MemoryVectorIndex.add()         ← 写入向量索引
  ├── MemoryBM25Index.add()           ← 写入 BM25 索引
  └── ChunkStore.put()                ← 写入知识块存储

POST /search
  ├── QueryRewriter.rewrite()         ← LLM 查询改写
  ├── EmbeddingClient.embed_text()    ← 查询向量化
  ├── MemoryVectorIndex.search()      ← 向量检索
  ├── MemoryBM25Index.search()        ← BM25 检索 (jieba 分词)
  ├── rrf_fusion()                    ← RRF 融合
  ├── Reranker.rerank()               ← LLM 重排序
  └── SearchResult                    ← 组装返回
```

---

## 环境说明

- **LLM 模型**: doubao-seed-2-0-pro-260215（火山引擎 ARK）
- **Embedding 模型**: doubao-embedding-vision-251215
- **API 端点**: https://ark.cn-beijing.volces.com/api/v3
- **集成测试耗时约 5 分钟**，主要瓶颈为 LLM 推理（均为推理模型，单次调用 15-30s）
