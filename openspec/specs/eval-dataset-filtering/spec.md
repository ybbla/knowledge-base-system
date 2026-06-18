# Eval Dataset Filtering

## Purpose

提供多维度的评测数据集筛选能力，支持按文档、分类、难度、来源、时间、关键词、随机抽样等条件灵活选择评测范围，实现快速验证、回归测试、定向优化等场景需求。

## Requirements

### Requirement: 按文档 ID 筛选

系统 SHALL 支持按文档 ID 筛选评测数据集。

#### Scenario: 指定单个文档 ID 筛选

- **WHEN** 用户指定 `--doc-id doc_abc123` 参数运行评测
- **THEN** 系统 SHALL 只运行来源为 `doc_abc123` 的评测查询
- **AND** 输出 SHALL 显示筛选摘要（如 "筛选后: 4/62 条 (文档=doc_abc123)"）

#### Scenario: 指定不存在的文档 ID

- **WHEN** 用户指定一个不存在的文档 ID
- **THEN** 系统 SHALL 显示提示信息（如 "筛选后无评测数据"）
- **AND** 系统 SHALL 显示原始数据集的大小供参考

### Requirement: 按业务分类筛选

系统 SHALL 支持按业务分类筛选评测数据集。

#### Scenario: 按分类筛选

- **WHEN** 用户指定 `--category 检索` 参数
- **THEN** 系统 SHALL 只运行分类为"检索"的评测查询

#### Scenario: 分类不存在时

- **WHEN** 用户指定一个不存在的分类
- **THEN** 系统 SHALL 显示筛选后无数据的提示信息

### Requirement: 按难度筛选

系统 SHALL 支持按难度等级筛选评测数据集。

#### Scenario: 指定难度等级

- **WHEN** 用户指定 `--difficulty hard` 参数
- **THEN** 系统 SHALL 只运行难度为"hard"的评测查询

#### Scenario: 难度值验证

- **WHEN** 用户指定非法的难度值（如 `extreme`）
- **THEN** 系统 SHALL 显示错误提示
- **AND** 系统 SHALL 列出合法的难度选项（easy/medium/hard）

### Requirement: 按来源筛选

系统 SHALL 支持按数据来源（自动生成/人工标注）筛选评测数据集。

#### Scenario: 只评测自动生成的数据

- **WHEN** 用户指定 `--source auto` 参数
- **THEN** 系统 SHALL 只运行自动生成的评测查询

#### Scenario: 只评测人工标注的数据

- **WHEN** 用户指定 `--source manual` 参数
- **THEN** 系统 SHALL 只运行人工标注的评测查询

### Requirement: 按时间范围筛选

系统 SHALL 支持按生成时间筛选评测数据集。

#### Scenario: 只评测最近 N 天新增的数据

- **WHEN** 用户指定 `--since 7` 参数
- **THEN** 系统 SHALL 只运行最近 7 天内生成的评测查询

#### Scenario: 时间范围无匹配数据

- **WHEN** 指定的时间范围内没有评测数据
- **THEN** 系统 SHALL 显示提示信息并退出

### Requirement: 按查询关键词筛选

系统 SHALL 支持按查询文本的关键词模糊匹配筛选。

#### Scenario: 关键词模糊匹配

- **WHEN** 用户指定 `--query 并发` 参数
- **THEN** 系统 SHALL 只运行查询文本包含"并发"关键词的评测查询

#### Scenario: 大小写不敏感

- **GIVEN** 存在查询"批量上传并发限制"
- **WHEN** 用户指定 `--query 并发` 或 `--query 并发`（大小写不同）
- **THEN** 系统 SHALL 正确匹配该查询

### Requirement: 随机抽样评测

系统 SHALL 支持随机抽样评测，用于快速验证。

#### Scenario: 随机抽样 N 条

- **WHEN** 用户指定 `--sample 10` 参数
- **THEN** 系统 SHALL 从数据集中随机抽取 10 条查询
- **AND** 每次运行 SHALL 抽取不同的样本（保证随机性）

#### Scenario: 抽样数大于数据集大小

- **GIVEN** 数据集只有 5 条查询
- **WHEN** 用户指定 `--sample 10` 参数
- **THEN** 系统 SHALL 使用全部 5 条查询
- **AND** 输出 SHALL 说明实际使用的数量

### Requirement: 只评测上次失败的查询

系统 SHALL 支持只运行上次评测失败的查询（回归验证）。

#### Scenario: 运行上次失败的查询

- **GIVEN** 上次评测有 5 条查询未命中
- **WHEN** 用户指定 `--failed` 参数
- **THEN** 系统 SHALL 只运行这 5 条失败的查询

#### Scenario: 无上次失败记录

- **GIVEN** 没有历史评测结果或上次全部通过
- **WHEN** 用户指定 `--failed` 参数
- **THEN** 系统 SHALL 显示提示信息并退出

### Requirement: 多条件组合筛选

系统 SHALL 支持多个筛选条件的组合使用。

#### Scenario: 组合多个筛选条件

- **WHEN** 用户指定 `--since 7 --category 检索 --difficulty hard`
- **THEN** 系统 SHALL 应用所有条件的交集
- **AND** 输出 SHALL 显示完整的筛选摘要（如 "筛选后: 12/62 条 (最近7天, 分类=检索, 难度=hard)"）

#### Scenario: 组合后无数据

- **WHEN** 组合的筛选条件过于严格导致无数据
- **THEN** 系统 SHALL 显示提示信息
- **AND** 系统 SHALL 建议放宽筛选条件
