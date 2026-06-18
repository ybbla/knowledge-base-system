# Eval Result Persistence

## Purpose

实现评测结果的持久化存储、历史对比和可追溯查询，支持质量趋势分析、版本对比、回归验证等场景，构建完整的检索质量闭环管理体系。

## Requirements

### Requirement: 评测结果结构化存储

系统 SHALL 将每次评测的结果以结构化格式持久化存储。

#### Scenario: 评测结果文件命名规范

- **WHEN** 评测完成后保存结果
- **THEN** 文件名 SHALL 为 `eval_result_{YYYYMMDD}_{HHMMSS}.json`
- **AND** 文件 SHALL 存储在 `tests/evaluation/results/` 目录下

#### Scenario: 评测结果内容结构

- **WHEN** 保存评测结果
- **THEN** 文件 SHALL 包含 `metadata` 字段（运行时间、触发方式、查询总数、持续时间）
- **AND** 文件 SHALL 包含 `metrics` 字段（Recall@5、MRR、Keyword Recall@5 等核心指标）
- **AND** 文件 SHALL 包含 `details` 数组（每条查询的详细运行结果）

### Requirement: 最新结果快捷方式

系统 SHALL 维护最新评测结果的快捷引用。

#### Scenario: 更新 latest.json 链接

- **WHEN** 成功保存新的评测结果
- **THEN** 系统 SHALL 更新 `results/latest.json` 文件
- **AND** latest.json 的内容 SHALL 与最新的评测结果完全一致

#### Scenario: 首次运行时创建 latest.json

- **GIVEN** `results/` 目录下没有任何评测结果
- **WHEN** 运行第一次评测
- **THEN** 系统 SHALL 创建 `latest.json` 并写入评测结果

### Requirement: 历史结果对比

系统 SHALL 支持与上一次评测结果进行对比。

#### Scenario: 自动显示对比结果

- **GIVEN** 存在历史评测结果（latest.json 存在）
- **WHEN** 用户运行评测（未指定 `--no-compare`）
- **THEN** 系统 SHALL 在输出中显示与上次结果的指标对比
- **AND** 对比 SHALL 包含每个指标的变化方向（↑/↓/=）和变化百分比

#### Scenario: 无历史结果时跳过对比

- **GIVEN** 不存在历史评测结果
- **WHEN** 用户运行评测
- **THEN** 系统 SHALL 显示提示信息（"无历史评测数据"）
- **AND** 对比步骤 SHALL 被跳过

### Requirement: 分维度指标统计

系统 SHALL 在评测报告中按维度统计指标。

#### Scenario: 按难度维度统计

- **WHEN** 评测完成后生成报告
- **THEN** 系统 SHALL 按难度（easy/medium/hard）分别统计命中率
- **AND** 输出 SHALL 显示每个难度的命中数/总数/百分比

#### Scenario: 按分类维度统计

- **WHEN** 评测完成后生成报告
- **THEN** 系统 SHALL 按业务分类分别统计命中率
- **AND** 输出 SHALL 显示每个分类的命中数/总数/百分比

### Requirement: 评测结果可追溯

系统 SHALL 支持查看评测历史和详情。

#### Scenario: 列出所有评测历史

- **WHEN** 用户查看评测历史
- **THEN** 系统 SHALL 列出 `results/` 目录下的所有评测结果文件
- **AND** 列表 SHALL 包含运行时间、触发方式、核心指标

#### Scenario: 查看特定评测结果详情

- **WHEN** 用户指定查看某个评测结果文件
- **THEN** 系统 SHALL 显示该次评测的完整报告
- **AND** 报告 SHALL 包含每条查询的详细运行结果
