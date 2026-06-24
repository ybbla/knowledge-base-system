# Eval Result Persistence

## Purpose

实现评测结果的持久化存储、历史对比和可追溯查询，支持质量趋势分析、版本对比、回归验证等场景，构建完整的检索质量闭环管理体系。

## Requirements

（已移除：评测结果从独立时间戳 JSON 文件改为追加写入单一 `history.jsonl` 文件（参见 `eval-result-history` 规格），不再需要按时间戳命名独立文件、latest.json 快捷方式、自动对比报告、分维度统计和详情查看功能。）
