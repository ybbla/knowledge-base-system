# Evaluation Framework

## Purpose

建立知识库检索质量评测体系，包含大模型辅助标注、人工抽检确认的评测数据集和自动化指标计算脚本，用于持续评估检索链路的质量变化。

## Requirements

### Requirement: 评测数据集管理

系统 SHALL 通过入库自动生成和人工标注两种方式构建评测数据集。评测脚本仅执行检索，不触发入库。

#### Scenario: 数据集格式

- **WHEN** 加载评测数据集
- **THEN** 每条记录 SHALL 包含 `query`、`expected_chunk_ids`、`expected_content_contains`
- **AND** 记录可选包含 `doc_id` 和 `source` 元数据字段

#### Scenario: 数据集完整性校验

- **WHEN** 加载评测数据集
- **THEN** 系统校验每条记录包含必需的 `query` 字段
- **AND** 系统校验每条记录至少包含 `expected_chunk_ids` 或 `expected_content_contains` 之一
- **AND** 缺失必填字段的记录被跳过并报告

### Requirement: EvalItem 数据结构扩展

EvalItem 数据结构 SHALL 精简为仅包含评测必需的核心字段，`source_doc_id` 重命名为 `doc_id`。

#### Scenario: 核心字段

- **WHEN** 创建或加载评测数据
- **THEN** 每条记录 SHALL 包含 `query`（用户查询）
- **AND** 每条记录 SHALL 包含 `expected_chunk_ids`（期望命中的 chunk ID 列表）
- **AND** 每条记录 SHALL 包含 `expected_content_contains`（chunk 内容应包含的关键词列表，不参与指标计算，仅供人工参考）
- **AND** 每条记录 MAY 包含 `doc_id`（来源文档 ID）
- **AND** 每条记录 MAY 包含 `source`（`auto` 或 `manual`）
- **AND** 系统 SHALL NOT 要求 `source_doc_id`、`source_doc_title`、`category`、`difficulty`、`generated_at` 字段

### Requirement: 自动化指标计算

系统 SHALL 提供标准 Recall@K 和 MRR 两个检索质量指标。

#### Scenario: 计算标准 Recall@5

- **WHEN** 对 N 条标注查询执行检索，每条返回 top-5 结果
- **THEN** `Recall@5 = 每条查询的（命中数 / 期望总数）的平均值`
- **AND** 某查询命中 2 个期望 chunk（期望总数为 3）→ 该查询 Recall@5 = 2/3 ≈ 0.667
- **AND** 某查询命中 0 个期望 chunk → 该查询 Recall@5 = 0.0
- **AND** 某查询期望 chunk_ids 为空 → 该查询不计入汇总

#### Scenario: 计算 MRR

- **WHEN** 对 N 条标注查询执行检索
- **THEN** `MRR = 每条查询的第一个命中 chunk 排名倒数的均值`
- **AND** 首个命中排在第 1 位 → 贡献 1.0
- **AND** 首个命中排在第 3 位 → 贡献 1/3 ≈ 0.333
- **AND** 无命中 → 贡献 0.0
- **AND** 某查询期望 chunk_ids 为空 → 该查询不计入汇总

#### Scenario: 评测脚本可重复执行

- **WHEN** 在相同索引数据状态下多次运行评测脚本
- **THEN** 每次输出的 Recall@5 和 MRR 值稳定

#### Scenario: 评测输出简洁报告

- **WHEN** 评测完成
- **THEN** 脚本 SHALL 在控制台输出：运行时间、查询总数、Recall@5、MRR
- **AND** 完整结果 SHALL 追加写入 `results/history.jsonl`
- **AND** 系统 SHALL NOT 生成 Markdown 报告文件
