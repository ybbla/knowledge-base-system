# 📊 知识库检索评测

文档入库后 LLM 自动生成评测数据 → 人工确认合并 → 一键跑评测 → 结果追加到历史文件。

## ✨ 核心流程

```
入库自动生成 → datasets/doc_{id}_{date}.json
                      │
          merge_to_global.py (手动合并)
                      │
                      ▼
               eval_dataset.json (全局数据集)
                      │
              run_eval.py (无参数)
                      │
                      ▼
          results/history.jsonl (JSONL 追加)
```

## 🚀 快速开始

### 1. 入库文档 → 自动生成评测数据

文档入库成功后，系统自动在 `datasets/` 目录下为该文档生成评测数据（查询数量由 `AUTO_EVAL_QUERIES_PER_DOC` 配置，默认 3）。

```env
# 是否启用入库自动生成（默认 true）
AUTO_EVAL_ENABLED=true
# 每个文档生成的查询数量（默认 3）
AUTO_EVAL_QUERIES_PER_DOC=3
```

### 2. 审核合并到全局数据集

确认 `datasets/doc_{id}_{date}.json` 中的查询质量后，手动合并到全局数据集：

```bash
cd knowledge_base_system
python tests/evaluation/merge_to_global.py <doc_id>
```

人工标注（`"source": "manual"`）的条目不会被合并覆盖。

### 3. 运行评测

```bash
cd knowledge_base_system
python tests/evaluation/run_eval.py
```

评测无需任何参数，输出包含查询总数、Recall@5、MRR 和耗时。

### 4. 查看评测历史

```bash
cat tests/evaluation/results/history.jsonl | jq .
```

---

## 🏗️ 目录结构

```
tests/evaluation/
├── dataset.py            # EvalItem 数据模型 + load_dataset() + save_dataset()
├── gen_dataset.py        # LLM 自动生成评测数据（入库调用的纯 API）
├── storage.py            # 分文档存储 + JSONL 结果追加
├── metrics.py            # 标准 Recall@K + MRR + safe_mean
├── run_eval.py            # ★ 评测入口脚本（无参数）
├── merge_to_global.py     # ★ 手动合并分文档数据到全局数据集
│
├── tests/                # 单元测试
│   ├── test_gen_dataset.py
│   ├── test_storage.py
│   └── test_merge_to_global.py
│
├── __init__.py
├── README.md
├── eval_dataset.json      # 全局评测数据集（人工标注 + 合并后的自动生成）
├── datasets/              # 分文档自动生成数据
│   └── doc_{id}_{date}.json
└── results/
    └── history.jsonl      # 评测历史（JSONL 每行一条记录）
```

## 📊 评测指标

| 指标 | 说明 |
|------|------|
| **Recall@5** | 标准定义：每条查询的（命中数 / 期望总数）的平均值 |
| **MRR** | 首个命中 chunk 排名倒数的均值 |

## 📊 JSONL 历史记录格式

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

## 📝 人工标注

直接编辑 `eval_dataset.json`：

```json
[
  {
    "query": "你的查询问题",
    "expected_chunk_ids": ["chunk_id1"],
    "expected_content_contains": ["关键词1"],
    "doc_id": "doc_abc123",
    "source": "manual"
  }
]
```

`"source": "manual"` 是关键 — 合并时人工标注条目不会被自动生成数据覆盖。

## 🧪 运行测试

```bash
cd knowledge_base_system
pytest tests/evaluation/ -v
```

## ⚙️ 配置

```env
# 入库后自动生成评测数据（默认 true）
AUTO_EVAL_ENABLED=true
# 每个文档生成的查询数量（默认 3）
AUTO_EVAL_QUERIES_PER_DOC=3
```
