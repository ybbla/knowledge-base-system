# Eval Result Persistence（Delta）

## REMOVED Requirements

### Requirement: 评测结果结构化存储

**Reason**: 评测结果从独立时间戳 JSON 文件改为追加写入单一 `history.jsonl` 文件（参见 `eval-result-history` 新规格），不再需要按时间戳命名独立文件。
**Migration**: 每次评测结果通过 JSONL 单行记录存在 `results/history.jsonl` 中，用 `tail -1 results/history.jsonl | jq .` 查看最新结果。

### Requirement: 最新结果快捷方式

**Reason**: `latest.json` 快捷方式被 JSONL 文件的最后一行所取代，无需额外维护快捷方式文件。
**Migration**: 使用 `tail -1 results/history.jsonl | jq .` 获取最新结果。

### Requirement: 历史结果对比

**Reason**: 自动对比报告功能移除，用户可从 `history.jsonl` 中自行提取任意两条记录对比。简化评测脚本输出。
**Migration**: 使用 `jq` 对比 `history.jsonl` 中的任意两条记录。

### Requirement: 分维度指标统计

**Reason**: `category`、`difficulty` 元数据字段已从 EvalItem 中移除，无法按维度分组。报告生成功能移除。
**Migration**: 无替代方案。

### Requirement: 评测结果可追溯

**Reason**: 评测历史可追溯性由 `history.jsonl` 文件本身保证（按时间顺序排列、每条含完整信息），删除额外的查看/列表功能。
**Migration**: 使用 `cat results/history.jsonl` 或 `jq` 浏览完整历史。
