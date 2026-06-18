## MODIFIED Requirements

### Requirement: 评测数据集加载
系统 SHALL 支持加载多个来源的评测数据集（全局 + 分文档）。

**变更前**：仅从单个 `eval_dataset.json` 文件加载

**变更后**：同时从 `eval_dataset.json` 和 `datasets/*.json` 加载

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

**变更前**：仅包含 query、expected_chunk_ids、expected_content_contains

**变更后**：新增多个元数据字段

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

### Requirement: 评测脚本命令行扩展
评测脚本 SHALL 支持新增的筛选命令行参数。

**变更前**：仅支持基本的运行和输出控制

**变更后**：支持多维度筛选参数

#### Scenario: pytest 兼容新增参数
- **WHEN** 通过 pytest 运行评测并传递筛选参数
- **THEN** 参数 SHALL 正确传递并应用到筛选逻辑

#### Scenario: 命令行帮助信息完整
- **WHEN** 用户执行 `python test_evaluation.py --help`
- **THEN** 帮助信息 SHALL 列出所有支持的筛选参数
- **AND** 帮助信息 SHALL 包含使用示例
