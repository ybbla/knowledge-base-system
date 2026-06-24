## 1. 数据模型精简

- [x] 1.1 重写 `dataset.py`：`EvalItem` 仅保留 `query`、`expected_chunk_ids`、`expected_content_contains`、`doc_id`（原 `source_doc_id` 重命名）、`source` 五个字段；新增 `save_dataset()` 函数；`load_dataset()` 和 `from_dict()` 使用新字段名，不保留旧字段的向后兼容
- [x] 1.2 重写 `test_models.py` 或新增测试验证新 `EvalItem` 字段完整性和 `load_dataset()`/`save_dataset()` 的正确性

## 2. 存储层精简

- [x] 2.1 重写 `storage.py`：保留 `init_storage()`（创建 `datasets/` / `results/` 目录）和 `save_per_doc_dataset()`（分文档存储，`items` 中字段对应新 EvalItem）；新增 `append_eval_result()`（JSONL 追加写入 `results/history.jsonl`，每条记录含 `timestamp`、`search_params`、`metrics`、`query_count`）；删除 `merge_to_global_dataset()`、`save_eval_result()`、`load_all_datasets()`、`load_latest_eval_result()`
- [x] 2.2 重写 `test_storage.py`：覆盖 `save_per_doc_dataset()` 输出格式验证和 `append_eval_result()` JSONL 追加写入正确性

## 3. 评测数据生成精简

- [x] 3.1 重写 `gen_dataset.py`：删除 CLI 入口（`main()`、`argparse`、`_load_chunks()`、`_load_existing()`、`_auto_count()`）；保留 `_generate()`、`_validate_annotations()`、`generate_for_chunks()`；LLM 提示词改为按 `target_count` 参数生成查询，覆盖直接询问、口语化改写、模糊查询三个角度；`generate_for_chunks` 签名中的 `query_count` 参数保留，从 `settings.auto_eval_queries_per_doc` 读取
- [x] 3.2 更新 `ingestion/pipeline.py` 的 `_trigger_eval_data_generation()`：变量名 `source_doc_id` → `doc_id`；删除 `source_doc_title`、`difficulty`、`generated_at` 等已移除字段的赋值
- [x] 3.3 确认 `app/core/config.py` 中 `auto_eval_enabled` 和 `auto_eval_queries_per_doc` 保持不变（默认 3）
- [x] 3.4 重写 `test_gen_dataset.py`：覆盖核心生成逻辑 `generate_for_chunks()` 和 `_validate_annotations()` 的测试；删除旧 CLI 相关测试用例

## 4. 指标计算更新

- [x] 4.1 更新 `metrics.py`：`recall_at_k()` 改为标准定义（返回 `命中数/期望总数` 而非二值 0/1）；保留 `mrr()` 和 `safe_mean()`；删除 `recall_by_keywords()`（`expected_content_contains` 不再参与指标计算，仅供人工参考）；添加完整中文注释

## 5. 新增模块

- [x] 5.1 新建 `run_eval.py`：评测触发脚本（无参数），流程为 → 加载 `eval_dataset.json` → 从 `app.core.deps` 初始化检索索引 → 遍历每个 query 调用 `retrieval_pipeline.search(query, top_k=5)` → 计算标准 Recall@5 和 MRR → 控制台输出简要报告（运行时间、查询总数、Recall@5、MRR）→ 调用 `storage.append_eval_result()` 追加写入 `history.jsonl`（记录当前 `settings` 中的检索参数：`rewrite`、`vector_top_k`、`bm25_top_k`、`rrf_k`、`rerank`、`top_k`）
- [x] 5.2 新建 `merge_to_global.py`：手动合并脚本，接受一个文档 ID 参数，将该文档的 `datasets/doc_{id}_{date}.json` 中的数据按 query 去重后合并到 `eval_dataset.json`，人工标注（`source: "manual"`）的条目不被覆盖
- [x] 5.3 新建测试文件验证 `run_eval.py` 和 `merge_to_global.py` 的核心逻辑

## 6. 删除冗余模块和文件

- [x] 6.1 删除 `filter.py` 和 `test_filter.py`
- [x] 6.2 删除 `tune_params.py`
- [x] 6.3 删除 `test_evaluation.py`（被 `run_eval.py` 替代）
- [x] 6.4 删除 `test_evaluation_integration.py`
- [x] 6.5 清理 `tests/conftest.py` 中的 `--eval-*` pytest 自定义参数注册
- [x] 6.6 删除旧数据文件：`eval_dataset.json`、`datasets/` 目录下所有 `*.json`、`results/` 目录下所有 `*.json`（`results/` 目录本身保留，供 `history.jsonl` 使用）
- [x] 6.7 删除 `tests/evaluation/__pycache__/` 下的旧 `.pyc` 文件

## 7. 文档和注释

- [x] 7.1 重写 `tests/evaluation/README.md`：反映新的目录结构和模块职责，删除 CLI 参数、筛选器使用等已移除功能的说明，保留快速开始和核心概念
- [x] 7.2 为所有保留 .py 文件的函数和类添加完整的中文文档字符串（docstring）和关键逻辑行内注释
- [x] 7.3 更新 `__init__.py`：添加包级说明文本

## 8. 端到端验证

- [x] 8.1 入库一篇文档，验证 `datasets/` 下生成评测数据文件，item 使用新的 EvalItem 字段名（`doc_id` 而非 `source_doc_id`）
- [x] 8.2 运行 `merge_to_global.py` 将该文档数据合并到 `eval_dataset.json`，验证去重和保护人工标注逻辑
- [x] 8.3 运行 `run_eval.py`，验证 `results/history.jsonl` 追加了一条记录，且记录包含完整的时间、检索参数和指标信息
- [x] 8.4 运行全部 evaluation 测试 `pytest tests/evaluation/ -v`，确保无失败
