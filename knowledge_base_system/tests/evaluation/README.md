# 知识库检索评测

文档入库后 LLM 自动生成评测数据 → 人工确认合并 → 一键跑评测 → 结果追加到历史文件。

## 核心流程

```
入库自动生成 → datasets/doc_{id}_{date}.json
                      │
          merge_to_global.py (手动合并)
                      │        去重键: (doc_id, query)
                      │        过期标注: 自动过滤
                      ▼
               eval_dataset.json (全局数据集)
                      │
              run_eval.py (无参数)
                      │        步骤 2: chunk_store.get_batch 过滤过期
                      ▼
          results/history.jsonl (JSONL 追加)
```

## 快速开始

### 1. 入库文档 → 自动生成评测数据

文档入库成功后，系统自动在 `datasets/` 目录下为该文档生成评测数据。超过 40 个知识块的大文档会自动分片生成，避免遗漏尾部内容。

```env
# 是否启用入库自动生成（默认 true）
AUTO_EVAL_ENABLED=true
# 每个文档生成的查询数量（默认 3）
AUTO_EVAL_QUERIES_PER_DOC=3
```

**注意**：同一文档重入库后，旧数据集文件会被自动删除，避免过期标注混入评测。

### 2. 审核合并到全局数据集

确认 `datasets/doc_{id}_{date}.json` 中的查询质量后，手动合并到全局数据集：

```bash
cd knowledge_base_system
python tests/evaluation/merge_to_global.py <doc_id>
```

- 去重键为 `(doc_id, query)`，不同文档的同名 query 不会互相覆盖
- `"source": "manual"` 的条目不会被自动生成数据覆盖
- 合并时自动携带 `doc_version` 字段

### 3. 运行评测

```bash
cd knowledge_base_system
python tests/evaluation/run_eval.py
```

评测分四步：
1. 加载全局数据集
2. **过滤过期标注** — 通过 `chunk_store.get_batch()` 查询预期 chunk 是否仍存在，全部失效的条目自动跳过
3. 重建检索索引
4. 逐条查询并计算 Recall@5 + MRR

### 4. 查看评测历史

```bash
cat tests/evaluation/results/history.jsonl | jq .
```

---

## 目录结构

```
tests/evaluation/
├── dataset.py            # EvalItem 数据模型 + load_dataset() + save_dataset()
├── gen_dataset.py        # LLM 自动生成评测数据（入库调用的纯 API）
├── storage.py            # 分文档存储（写入前删旧文件）+ JSONL 结果追加
├── metrics.py            # 标准 Recall@K + MRR + safe_mean
├── run_eval.py            # ★ 评测入口脚本（无参数）
├── merge_to_global.py     # ★ 手动合并分文档数据到全局数据集
├── __init__.py
├── README.md
├── eval_dataset.json      # 全局评测数据集（人工标注 + 合并后的自动生成）
├── datasets/              # 分文档自动生成数据
│   └── doc_{id}_{date}.json
└── results/
    └── history.jsonl      # 评测历史（JSONL 每行一条记录）
```

## 评测指标

| 指标 | 说明 |
|------|------|
| **Recall@5** | 每条查询 top-5 命中数 / 期望总数，取所有查询的平均值 |
| **MRR** | 首个命中 chunk 排名倒数的均值（第1→1.0, 第3→0.333, 未命中→0） |

## JSONL 历史记录格式

`results/history.jsonl` 每行一条记录：

```json
{
  "timestamp": "2026-06-23T10:30:00",
  "search_params": {
    "rewrite": true,
    "vector_top_k": 30,
    "bm25_top_k": 30,
    "rrf_k": 60,
    "rerank": true,
    "top_k": 5
  },
  "metrics": {
    "recall_at_5": 0.667,
    "mrr": 0.583
  },
  "query_count": 50
}
```

## 数据集格式

### 分文档数据集 (datasets/doc_{id}_{date}.json)

```json
{
  "metadata": {
    "doc_id": "doc_abc123456789",
    "doc_title": "Python入门指南",
    "doc_version": 1,
    "generated_at": "2026-06-25T10:30:00",
    "generated_by": "auto-ingest",
    "chunk_count": 5,
    "query_count": 3
  },
  "items": [
    {
      "query": "Python是什么类型的编程语言？",
      "expected_chunk_ids": ["chunk_a1b2c3d4e5f6"],
      "expected_content_contains": ["解释型", "面向对象", "Guido van Rossum"],
      "doc_id": "doc_abc123456789",
      "doc_version": 1,
      "source": "auto"
    }
  ]
}
```

### 全局数据集 (eval_dataset.json)

```json
[
  {
    "query": "Python是什么类型的编程语言？",
    "expected_chunk_ids": ["chunk_a1b2c3d4e5f6"],
    "expected_content_contains": ["解释型", "面向对象"],
    "doc_id": "doc_abc123456789",
    "doc_version": 1,
    "source": "auto"
  }
]
```

## 人工标注

直接编辑 `eval_dataset.json`，设置 `"source": "manual"`：

```json
[
  {
    "query": "你的查询问题",
    "expected_chunk_ids": ["chunk_id1"],
    "expected_content_contains": ["关键词1"],
    "doc_id": "doc_abc123",
    "doc_version": 1,
    "source": "manual"
  }
]
```

`"source": "manual"` 是关键 — 合并时人工标注条目不会被自动生成数据覆盖。

## 运行测试

```bash
cd knowledge_base_system
pytest tests/evaluation/ -v
```

## 配置

```env
# 入库后自动生成评测数据（默认 true）
AUTO_EVAL_ENABLED=true
# 每个文档生成的查询数量（默认 3）
AUTO_EVAL_QUERIES_PER_DOC=3
```

## 生命周期

```
文档初次入库 → datasets/doc_{id}_v1.json 生成
文档重入库   → 旧文件自动删除 → datasets/doc_{id}_v2.json 生成（doc_version=2）
merge_to_global → 按 (doc_id, query) 去重合并到 eval_dataset.json
run_eval    → 步骤 2 过滤 chunk 不存在的过期标注 → 评测 → history.jsonl
```
