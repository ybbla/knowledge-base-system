# Eval Result History

## Purpose

评测结果以 JSONL 格式追加写入单一历史文件，每条记录包含完整的时间、检索参数和指标信息，支持用 `grep`/`jq` 等标准工具进行时间序列分析。

## Requirements

### Requirement: JSONL 追加写入评测历史

系统 SHALL 在每次评测完成后，将结果以一行 JSON 记录的形式追加写入 `results/history.jsonl` 文件。

#### Scenario: 首次运行评测创建历史文件

- **GIVEN** `results/history.jsonl` 文件不存在
- **WHEN** 运行评测脚本
- **THEN** 系统 SHALL 创建 `results/history.jsonl` 文件
- **AND** 系统 SHALL 在文件中写入第一行 JSON 记录

#### Scenario: 追加写入已有历史文件

- **GIVEN** `results/history.jsonl` 文件已存在
- **WHEN** 运行评测脚本
- **THEN** 系统 SHALL 在文件末尾追加一行新的 JSON 记录
- **AND** 已有记录 SHALL 保持不变

### Requirement: 评测历史记录内容结构

每条历史记录 SHALL 包含完整的时间戳、检索参数配置和评测指标值。

#### Scenario: 记录包含时间戳

- **WHEN** 写入评测历史记录
- **THEN** 记录 SHALL 包含 `timestamp` 字段
- **AND** 时间戳 SHALL 使用 ISO 8601 格式（如 `2026-06-23T10:30:00`）

#### Scenario: 记录包含检索参数

- **WHEN** 写入评测历史记录
- **THEN** 记录 SHALL 包含 `search_params` 对象
- **AND** `search_params` SHALL 包含 `rewrite`（布尔值，是否启用查询改写）
- **AND** `search_params` SHALL 包含 `vector_top_k`（向量检索返回数量）
- **AND** `search_params` SHALL 包含 `bm25_top_k`（BM25 检索返回数量）
- **AND** `search_params` SHALL 包含 `rrf_k`（RRF 融合参数 k）
- **AND** `search_params` SHALL 包含 `rerank`（布尔值，是否启用重排序）
- **AND** `search_params` SHALL 包含 `top_k`（最终返回 top-K）

#### Scenario: 记录包含评测指标

- **WHEN** 写入评测历史记录
- **THEN** 记录 SHALL 包含 `metrics` 对象
- **AND** `metrics` SHALL 包含 `recall_at_5`（float，标准 Recall@5）
- **AND** `metrics` SHALL 包含 `mrr`（float，MRR 值）
- **AND** 记录 SHALL 包含 `query_count`（int，参与评测的查询总数）
