# Eval Dataset Filtering（Delta）

## REMOVED Requirements

### Requirement: 按文档 ID 筛选

**Reason**: 整个筛选模块连同 `filter.py` 一起移除。评测统一使用全量数据集，筛选需求可通过 `jq`/`grep` 对 `eval_dataset.json` 文件直接操作实现。
**Migration**: 使用 `jq '.[] | select(.doc_id == "doc_xxx")' eval_dataset.json` 实现按文档筛选。

### Requirement: 按业务分类筛选

**Reason**: `category` 字段从 EvalItem 中移除，筛选模块整体删除。
**Migration**: 无替代方案，如需按主题区分评测数据，建议在人工标注时通过 query 文本关键词作为标记。

### Requirement: 按难度筛选

**Reason**: `difficulty` 字段从 EvalItem 中移除，筛选模块整体删除。
**Migration**: 无替代方案。

### Requirement: 按来源筛选

**Reason**: 筛选模块整体删除。评测统一使用全量数据集（自动生成 + 人工标注混合）。
**Migration**: 使用 `jq '.[] | select(.source == "manual")' eval_dataset.json` 实现按来源筛选。

### Requirement: 按时间范围筛选

**Reason**: `generated_at` 字段从 EvalItem 中移除，筛选模块整体删除。
**Migration**: 无替代方案。

### Requirement: 按查询关键词筛选

**Reason**: 筛选模块整体删除。
**Migration**: 使用 `grep '"query"' eval_dataset.json` 实现按关键词筛选。

### Requirement: 随机抽样评测

**Reason**: 筛选模块整体删除。
**Migration**: 使用 `shuf` 或 Python 一行脚本随机抽取 N 条查询。

### Requirement: 只评测上次失败的查询

**Reason**: 筛选模块整体删除，`_last_passed` 字段从 EvalItem 中移除。
**Migration**: 从 `results/history.jsonl` 中提取上次失败的查询，手动过滤数据集。

### Requirement: 多条件组合筛选

**Reason**: 筛选模块整体删除。
**Migration**: 使用 `jq` 链式过滤实现组合条件。
