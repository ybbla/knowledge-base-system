# Eval Dataset Filtering

## Purpose

提供多维度的评测数据集筛选能力，支持按文档、分类、难度、来源、时间、关键词、随机抽样等条件灵活选择评测范围，实现快速验证、回归测试、定向优化等场景需求。

## Requirements

（已移除：整个筛选模块连同 `filter.py` 一起移除。评测统一使用全量数据集，筛选需求可通过 `jq`/`grep` 对 `eval_dataset.json` 文件直接操作实现。）
