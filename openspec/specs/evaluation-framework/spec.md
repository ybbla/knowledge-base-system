# Evaluation Framework

## Purpose

建立知识库检索质量评测体系，包含大模型辅助标注、人工抽检确认的评测数据集和自动化指标计算脚本，用于持续评估检索链路的质量变化。

## Requirements

### Requirement: 评测数据集管理

系统 SHALL 提供结构化评测数据集，包含人工标注和自动生成的混合查询集。标注工作支持一次性准备阶段（源文档入库后，大模型辅助标注，人工确认）和入库自动生成两种模式。评测脚本仅执行检索，不重复入库。

#### Scenario: 数据集格式

- **WHEN** 加载评测数据集
- **THEN** 每条记录包含 `query`（用户查询）、`expected_chunk_ids`（期望命中的 chunk ID 列表）和 `expected_content_contains`（chunk 内容应包含的关键词列表）
- **AND** 记录可选择性包含元数据字段：`source_doc_id`、`source_doc_title`、`category`、`difficulty`、`source`、`generated_at`

#### Scenario: 一次性准备阶段回填 chunk_id

- **WHEN** 构建评测数据集
- **THEN** 先将源文档入库，记录系统实际生成的 chunk_id
- **AND** 将 query、候选 chunk_id 和 chunk 内容提供给大模型，辅助生成各查询的 `expected_chunk_ids` 和 `expected_content_contains`
- **AND** 人工抽检/确认大模型标注结果后固定数据集，评测脚本不再修改

#### Scenario: 数据集完整性校验

- **WHEN** 加载评测数据集
- **THEN** 系统校验每条记录包含必需的 `query` 和 `expected_chunk_ids` 字段
- **AND** 缺失字段的记录被标记并报告

### Requirement: 评测数据集多源加载

系统 SHALL 支持加载多个来源的评测数据集（全局 + 分文档）。

#### Scenario: 合并加载所有数据集

- **WHEN** 运行评测时未指定特定数据集文件
- **THEN** 系统 SHALL 加载 `eval_dataset.json` 中的所有条目
- **AND** 系统 SHALL 加载 `datasets/` 目录下所有分文档的评测数据
- **AND** 系统 SHALL 按查询文本进行全局去重
- **AND** 重复条目 SHALL 保留先出现的版本（全局文件优先于分文档文件）

#### Scenario: 指定单个数据集文件

- **WHEN** 用户通过 `--dataset` 参数指定特定文件
- **THEN** 系统 SHALL 只加载该指定文件的内容
- **AND** 系统 SHALL NOT 加载其他文件

### Requirement: EvalItem 数据结构扩展

EvalItem 数据结构 SHALL 扩展以支持筛选和元数据管理。

#### Scenario: 保留向后兼容性

- **GIVEN** 旧格式的评测数据文件（无新增元数据字段）
- **WHEN** 加载旧格式数据
- **THEN** 系统 SHALL 正常解析
- **AND** 缺失的元数据字段 SHALL 使用默认值（如 difficulty 默认 "medium"）

#### Scenario: 新增元数据字段完整

- **WHEN** 处理新格式的评测数据
- **THEN** 系统 SHALL 正确识别 `source_doc_id` 字段
- **AND** 系统 SHALL 正确识别 `source_doc_title` 字段
- **AND** 系统 SHALL 正确识别 `category` 字段
- **AND** 系统 SHALL 正确识别 `difficulty` 字段
- **AND** 系统 SHALL 正确识别 `source` 字段
- **AND** 系统 SHALL 正确识别 `generated_at` 字段

### Requirement: 自动化指标计算

系统 SHALL 提供自动化脚本计算 Recall@5 和 MRR 两个检索质量指标。

#### Scenario: 计算 Recall@5

- **WHEN** 对 20 条标注查询执行检索，每条返回 top-5 结果
- **THEN** `Recall@5 = 期望 chunk 在 top-5 中出现的比例`
- **AND** 若某查询的任一 `expected_chunk_id` 出现在 top-5 结果中，该查询计为命中

#### Scenario: 计算 MRR

- **WHEN** 对 20 条标注查询执行检索
- **THEN** `MRR = 第一个命中 chunk 排名的倒数均值`
- **AND** 若某查询无命中，该查询贡献为 0

#### Scenario: 评测脚本可重复执行

- **WHEN** 在相同索引数据状态下多次运行评测脚本
- **THEN** 每次输出的 Recall@5 和 MRR 值稳定（评测脚本仅检索，不入库；LLM 检索管线的非确定性是被测对象的一部分）

#### Scenario: 评测输出人类可读报告

- **WHEN** 评测完成
- **THEN** 脚本输出包含：总查询数、Recall@5、MRR、每条查询的命中详情（期望 chunk_id、实际排名、是否命中）
- **AND** 报告以 Markdown 格式保存到 `tests/results/`

### Requirement: 评测集成到测试流程

系统 SHALL 支持评测作为 pytest 兼容的测试用例运行，或在 CI 中作为独立脚本运行。

#### Scenario: pytest 兼容

- **WHEN** 运行 `pytest tests/evaluation/`
- **THEN** 评测用例执行检索并验证 Recall@5 和 MRR 不低于预设基线值

#### Scenario: pytest 兼容新增筛选参数

- **WHEN** 通过 pytest 运行评测并传递筛选参数
- **THEN** 参数 SHALL 正确传递并应用到筛选逻辑

#### Scenario: 独立脚本运行

- **WHEN** 运行 `python tests/evaluation/test_evaluation.py`
- **THEN** 脚本执行全量评测并输出 Markdown 报告

#### Scenario: 命令行帮助信息完整

- **WHEN** 用户执行 `python tests/evaluation/test_evaluation.py --help`
- **THEN** 帮助信息 SHALL 列出所有支持的筛选参数
- **AND** 帮助信息 SHALL 包含使用示例
