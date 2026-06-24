# Eval Dataset Auto-generation

## Purpose

文档入库时自动生成评测数据，包括查询语句、预期 chunk ID、关键词标注。支持后台异步生成、标注校验、增量合并到全局数据集，实现评测数据的零成本积累。

## Requirements

### Requirement: 文档入库自动触发生成评测数据

文档入库完成后，系统 SHALL 在后台自动为该文档生成评测数据。

#### Scenario: 成功入库后自动生成

- **GIVEN** 系统配置开启了自动评测数据生成（`auto_eval_enabled=true`）
- **WHEN** 一篇文档成功完成入库流程（解析、抽取、索引构建完成）
- **THEN** 系统 SHALL 触发异步任务为该文档生成评测数据
- **AND** 生成过程 SHALL 不阻塞主入库流程

#### Scenario: 配置关闭时不触发生成

- **GIVEN** 系统配置关闭了自动评测数据生成（`auto_eval_enabled=false`）
- **WHEN** 一篇文档成功完成入库流程
- **THEN** 系统 SHALL NOT 触发生成评测数据

### Requirement: 为单个文档生成评测查询

系统 SHALL 为每个新入库的文档生成评测查询，数量由 `auto_eval_queries_per_doc` 配置项决定（默认 3），每条查询覆盖不同的提问角度。

#### Scenario: 生成查询覆盖多个角度

- **GIVEN** 一篇包含知识块的文档
- **WHEN** 触发生成评测数据
- **THEN** 系统 SHALL 调用 LLM 生成配置数量的查询
- **AND** 查询 SHALL 覆盖：直接询问（X 是什么？）、口语化改写（怎么判断 X？）、模糊查询（用不精确表述问同一问题）三类角度
- **AND** 查询 SHALL 来源于文档的实际知识块内容

#### Scenario: 单 chunk 文档处理

- **GIVEN** 一篇文档仅包含 1 个知识块
- **WHEN** 触发生成评测数据
- **THEN** 系统 SHALL 仍然生成 3 条查询
- **AND** 查询 SHALL 从不同角度提问该知识块的内容

### Requirement: 自动标注预期 chunk ID

系统 SHALL 为每条生成的查询自动标注预期命中的知识块 ID。

#### Scenario: 单 chunk 查询标注

- **GIVEN** 一条查询明确对应某个知识块
- **WHEN** LLM 生成标注
- **THEN** 系统 SHALL 在 `expected_chunk_ids` 中包含该 chunk ID

#### Scenario: 跨 chunk 查询标注

- **GIVEN** 一条查询涉及多个知识块
- **WHEN** LLM 生成标注
- **THEN** 系统 SHALL 在 `expected_chunk_ids` 中包含所有相关的 chunk ID
- **AND** 关联的 chunk 数量 SHALL 不超过 3 个

### Requirement: 自动提取关键词标注

系统 SHALL 为每条生成的查询自动提取预期包含的关键词。

#### Scenario: 关键词提取

- **GIVEN** 一条生成的查询及其对应的知识块内容
- **WHEN** 提取关键词
- **THEN** 系统 SHALL 从知识块正文中提取 3-5 个关键词
- **AND** 关键词 SHALL 精确匹配正文内容
- **AND** 关键词 SHALL 存储在 `expected_content_contains` 字段中

### Requirement: 评测数据分文档存储

系统 SHALL 将每个文档生成的评测数据独立存储。

#### Scenario: 存储文件命名规范

- **WHEN** 保存某个文档的评测数据
- **THEN** 文件 SHALL 命名为 `doc_{doc_id}_{date}.json`
- **AND** 文件 SHALL 存储在 `tests/evaluation/datasets/` 目录下

#### Scenario: 存储文件内容格式

- **WHEN** 保存评测数据文件
- **THEN** 文件 SHALL 包含 `metadata` 字段（文档 ID、标题、生成时间、chunk 数量、查询数量）
- **AND** 文件 SHALL 包含 `items` 数组（评测查询的详细内容）

### Requirement: 生成失败不影响主流程

评测数据生成失败 SHALL 不影响文档入库的成功状态。

#### Scenario: LLM 调用失败

- **WHEN** 生成评测数据时 LLM 调用失败
- **THEN** 系统 SHALL 记录错误日志
- **AND** 系统 SHALL 终止生成流程
- **AND** 文档入库状态 SHALL 保持为成功

#### Scenario: 存储写入失败

- **WHEN** 保存评测数据文件时发生 IO 错误
- **THEN** 系统 SHALL 记录错误日志
- **AND** 系统 SHALL 终止保存流程

### Requirement: 合并到全局评测集

系统 SHALL 将新生成的评测数据增量合并到全局评测集中。

#### Scenario: 增量合并去重

- **GIVEN** 全局评测集中已存在某些查询
- **WHEN** 合并新生成的评测数据
- **THEN** 系统 SHALL 按查询文本去重
- **AND** 只有新增的查询 SHALL 被添加到全局数据集

#### Scenario: 保护人工标注数据

- **GIVEN** 全局评测集中包含人工标注的查询
- **WHEN** 合并新生成的数据
- **THEN** 人工标注的数据 SHALL 保持不变
- **AND** 自动生成的数据 SHALL 不会覆盖或修改人工标注
