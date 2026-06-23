## Why

当前评测体系功能过度膨胀——包含命令行手动生成、8 维度筛选器、参数网格调优、pytest 集成、Markdown 报告生成等多个模块，核心评测流程被淹没在大量辅助功能中。`EvalItem` 数据模型字段冗余（10 个字段 + 1 个运行时字段），实际评测中大多数字段未被使用。评测结果分散在带时间戳的独立文件中，缺乏统一的历史记录视图。

此次重构旨在：精简数据模型为最小可用集，收敛数据生成路径（仅入库自动触发），简化评测执行（无参数、单脚本、追加记录），删除未被实际使用的手动生成、筛选器和参数调优模块。

## What Changes

- **评测数据模型精简**：`EvalItem` 仅保留 `query`、`expected_chunk_ids`、`expected_content_contains`、`doc_id`、`source` 五个字段
- **每文档生成评测数据**：LLM 自动生成查询，覆盖三个角度（直接询问、口语化改写、模糊查询），生成数量通过 `auto_eval_queries_per_doc` 配置
- **入库异步生成**：保留 `_trigger_eval_data_generation()`，去掉 CLI 手动生成入口（`main()`、argparse 全部删除），只保留入库自动触发路径
- **分文档存储 + 手动合并**：每个文档的评测数据写入 `datasets/doc_{id}_{date}.json`，`merge_to_global.py` 脚本手动将指定文档合并到 `eval_dataset.json`
- **评测执行极简化**：`run_eval.py`（无参数），加载全局数据集 → 初始化检索索引 → 遍历查询 → 计算标准 Recall@K 和 MRR → 追加写入 `results/history.jsonl`
- **评测结果追加写入**：每次结果追加到 `results/history.jsonl`，每行 JSON 含 `timestamp`、`search_params`（rewrite / vector_top_k / bm25_top_k / rrf_k / rerank / top_k）、`metrics`（recall_at_5、mrr）、`query_count`
- **指标标准化**：Recall@K 改为标准定义 `命中数/期望总数`；保留 MRR；删除 `recall_by_keywords`
- **旧数据文件处置**：存量 `eval_dataset.json`、`datasets/*.json`、`results/*.json` 直接删除，采用全新的数据模型和文件结构，不保留向后兼容
- **BREAKING**：删除 `FilterCriteria`、`DatasetFilter`、8 维度筛选、pytest 评测集成、参数网格搜索、Markdown 报告、`--category`/`--count`/`--dry-run` 等 CLI 参数；删除旧格式数据文件

## Capabilities

### New Capabilities

- `eval-result-history`: 评测结果以 JSONL 追加写入单一历史文件，每条记录含时间、检索参数配置、Recall@K 和 MRR 值

### Modified Capabilities

- `evaluation-framework`: EvalItem 数据模型精简到 5 个字段（`source_doc_id` 重命名为 `doc_id`）；Recall@K 改为标准定义（命中数/期望总数）；删除 pytest 集成和 Markdown 报告
- `eval-dataset-auto-generation`: 删除 CLI 手动生成入口；LLM 提示词改为精确生成配置数量的查询；删除 `merge_to_global_dataset` 的自动合并，改为独立手动合并脚本
- `eval-dataset-filtering`: **删除** — 整个筛选能力移除
- `eval-result-persistence`: 结果存储从独立时间戳文件改为追加到单一 history.jsonl 文件

## Impact

| 影响范围 | 说明 |
|----------|------|
| `tests/evaluation/` | 重写 `dataset.py`、`metrics.py`、`gen_dataset.py`、`storage.py`、`test_storage.py`、`test_gen_dataset.py`；删除 `filter.py`、`tune_params.py`、`test_evaluation.py`、`test_filter.py`、`test_evaluation_integration.py`；新增 `run_eval.py`、`merge_to_global.py`；删除 `eval_dataset.json`、`datasets/`、`results/` 下的旧数据文件 |
| `ingestion/pipeline.py` | `_trigger_eval_data_generation()` 适配精简后的生成 API |
| `app/core/config.py` | 保留 `auto_eval_enabled` 和 `auto_eval_queries_per_doc` |
| `tests/conftest.py` | 删除所有 `--eval-*` pytest 自定义命令行参数 |

### 回滚计划

`git revert` 本次 commit 即可回到重构前状态。
