## Context

当前评测系统位于 `tests/evaluation/`，包含 10 个 Python 文件 + 数据目录。架构过度膨胀：8 维筛选器、参数网格调优、pytest 集成、Markdown 报告、CLI 手动生成等模块形成多层抽象，但实际使用中只需要「入库自动生成 → 人工调整 → 跑评测看指标」这条核心链路。

重构目标：砍掉未被使用的辅助模块，将剩余模块精简到最小可用集，使每个文件的职责单一且清晰。旧数据文件（`eval_dataset.json`、`datasets/`、`results/`）直接删除，采用全新的数据模型和文件结构。

## Goals / Non-Goals

**Goals:**
- 数据模型极简化：`EvalItem` 从 10 个字段减至 5 个核心字段，`source_doc_id` 重命名为 `doc_id`
- 数据生成收敛：仅保留入库异步触发一条路径，删除 CLI 手动生成
- 评测执行零配置：`run_eval.py` 无参数，一键运行
- 结果存储线性化：每次评测结果追加到 `results/history.jsonl`
- 指标标准化：Recall@K 改为标准定义（`命中数 / 期望总数`），保留 MRR

**Non-Goals:**
- 不改变 LLM 调用方式（仍通过 volcengine_client）
- 不改变入库主流程（`pipeline.py` 核心逻辑不动）
- 不新增外部依赖
- 不保留旧数据文件的向后兼容（全部删除，新开）

## Decisions

### 1. EvalItem 字段取舍

| 字段 | 决策 | 理由 |
|------|------|------|
| `query` | ✅ 保留 | 核心评测数据 |
| `expected_chunk_ids` | ✅ 保留 | 评测标注核心 |
| `expected_content_contains` | ✅ 保留 | 关键词辅助标注，供人工参考，不参与指标计算 |
| `doc_id` | ✅ 保留（`source_doc_id` 重命名） | 追溯来源用，去掉 `source_` 前缀 |
| `source` | ✅ 保留 | 区分 `auto`/`manual`，保护人工标注 |
| `source_doc_title` | ❌ 删除 | 可通过 doc_id 间接获取 |
| `category` | ❌ 删除 | 与筛选器一起删除 |
| `difficulty` | ❌ 删除 | 未被有效使用 |
| `generated_at` | ❌ 删除 | 分文档文件的 metadata 字段已足够 |
| `_last_passed` | ❌ 删除 | 与 --failed 筛选一起删除 |

### 2. 查询数量可配置（每文档 3 条为推荐默认值）

- 保留 `settings.auto_eval_queries_per_doc` 配置项，默认值 3
- LLM 提示词使用该配置值生成对应数量的查询，覆盖三个角度：直接询问、口语化改写、模糊查询
- 理由：保留灵活性，不同场景可调整（如初期用 3 条快速积累，常规部署可增至 5 条）

### 3. 评测结果采用 JSONL 追加写入

选择 JSONL（每行一条 JSON 记录）追加到 `results/history.jsonl` 文件：
- **优势**：易于 `grep`/`jq` 过滤分析、自然支持时间序列、无文件膨胀
- **每条记录结构**：
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

### 4. 删除的模块和确定依据

| 模块 | 删除理由 |
|------|----------|
| `filter.py` + `test_filter.py` | 8 维筛选能力在实际使用中极少用到 |
| `tune_params.py` | 参数调优为一次性任务，不常运行 |
| `test_evaluation.py` | pytest 集成 + 独立脚本入口，被 `run_eval.py` 替代 |
| `test_evaluation_integration.py` | CLI 兼容性/混合格式测试不再适用 |
| 旧数据文件 | 模型字段变化，不复用旧格式 |

### 5. 保留但需重写的文件

| 文件 | 处理方式 |
|------|----------|
| `test_storage.py` | 重写：覆盖 `save_per_doc_dataset()` + 新 `append_eval_result()` |
| `test_gen_dataset.py` | 重写：覆盖修改后的 `generate_for_chunks()`（固定 3 角度 + 可配数量） |

### 6. 新增的文件

| 文件 | 职责 |
|------|------|
| `run_eval.py` | 评测触发脚本（无参数），加载数据集 → 初始化索引 → 检索 → 指标 → 追加 history.jsonl |
| `merge_to_global.py` | 手动合并脚本，将指定 `doc_id` 的分文档数据合并到 `eval_dataset.json`，按 query 去重，保护 `source: "manual"` 条目 |

### 7. 文件最终结构

```
tests/evaluation/
├── dataset.py            # EvalItem（5 字段）+ load_dataset() + save_dataset()
├── gen_dataset.py        # LLM 自动生成（纯 API，无 CLI）
├── storage.py            # save_per_doc_dataset() + append_eval_result() + init_storage()
├── metrics.py            # recall_at_k（标准） + mrr + safe_mean
├── run_eval.py            # ★ 新增：评测入口脚本
├── merge_to_global.py     # ★ 新增：手动合并到全局数据集
├── test_gen_dataset.py    # 重写
├── test_storage.py        # 重写
├── __init__.py            # 包说明
├── eval_dataset.json      # 全局数据集（全新）
├── datasets/              # 分文档数据集（全新）
└── results/
    └── history.jsonl      # 评测历史（全新）
```

## Risks / Trade-offs

- **[风险] JSONL 文件无限增长** → 长期运行后文件可达 MB 级别，可在评测脚本中加大小提示
- **[风险] 删除筛选器后调试需手动过滤** → 可用 `jq`/`grep` 直接操作 `eval_dataset.json` 替代
- **[风险] 删除旧数据文件丢失历史标注** → 旧标注数据可在重构前手动备份到其他路径
- **[权衡] `expected_content_contains` 保留但不参与指标计算** → 字段作为人工参考标注保留，未来如需关键词匹配指标可再加回
