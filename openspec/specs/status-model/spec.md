# Status Model

## Purpose

定义知识库系统统一的状态模型。覆盖文档生命周期、知识块生命周期和资源处理状态。此规范为所有其他能力的状态引用提供唯一权威来源。

> 同步自 change `simplify-status-model`，日期 2026-06-19。

## Requirements

### Requirement: 文档状态定义

系统 SHALL 定义 DocStatus 为以下 4 个值的枚举：`processing`、`active`、`failed`、`deleted`。

- `processing`：文档已创建/上传，正在进行解析、语义抽取和索引
- `active`：文档已完成全部入库流程，可被搜索
- `failed`：文档处理过程中发生错误，`error_message` 记录失败原因
- `deleted`：文档被软删除，可恢复为 `active`

状态流转规则 SHALL 为：新建文档 → `processing` → `active` | `failed`；任意时刻可通过软删除/恢复在 `active` ⟷ `deleted` 之间切换。

#### Scenario: 文档创建时默认状态
- **WHEN** 创建新的 Document 记录
- **THEN** `status` SHALL 为 `processing`

#### Scenario: 文档入库成功
- **WHEN** 文档完成解析、语义抽取和索引全部步骤
- **THEN** `status` SHALL 变更为 `active`

#### Scenario: 文档入库失败
- **WHEN** 文档在解析、语义抽取或索引任一步骤发生异常
- **THEN** `status` SHALL 变更为 `failed`
- **AND** `error_message` SHALL 记录具体失败原因

#### Scenario: 文档软删除
- **WHEN** 对 `active` 或 `failed` 文档执行软删除
- **THEN** `status` SHALL 变更为 `deleted`

#### Scenario: 文档恢复
- **WHEN** 对 `deleted` 文档执行恢复
- **THEN** `status` SHALL 变更为 `active`

### Requirement: 知识块状态定义

系统 SHALL 定义 ChunkStatus 为以下 2 个值的枚举：`active`、`deleted`。

- `active`：知识块处于活跃状态，可被搜索
- `deleted`：知识块被软删除，不可被搜索

状态流转规则 SHALL 为：知识块创建即为 `active`；更新文档时旧知识块标记为 `deleted`；可通过软删除/恢复在 `active` ⟷ `deleted` 之间切换。

#### Scenario: 知识块创建时默认状态
- **WHEN** 创建新的 KnowledgeChunk
- **THEN** `status` SHALL 为 `active`

#### Scenario: 文档更新时旧知识块状态变更
- **WHEN** 文档被更新（新文档替换旧文档）
- **THEN** 旧文档下的所有 `active` 知识块 SHALL 标记为 `deleted`

#### Scenario: 知识块软删除
- **WHEN** 对 `active` 知识块执行软删除
- **THEN** `status` SHALL 变更为 `deleted`

#### Scenario: 知识块恢复
- **WHEN** 对 `deleted` 知识块执行恢复
- **THEN** `status` SHALL 变更为 `active`

### Requirement: 资源状态定义

系统 SHALL 定义 AssetStatus 为以下 2 个值的枚举：`ready`、`failed`。

- `ready`：资源已成功处理（下载校验通过、已上传到对象存储或已关联）
- `failed`：资源处理失败，`error_message` 记录失败原因

#### Scenario: 资源创建时默认状态
- **WHEN** 创建新的 Asset 记录
- **THEN** `status` SHALL 为 `ready`

#### Scenario: 资源处理失败
- **WHEN** 资源下载、校验或上传任一步骤失败
- **THEN** `status` SHALL 变更为 `failed`
- **AND** `error_message` SHALL 记录具体失败原因

### Requirement: 不定义知识块索引状态

系统 SHALL NOT 定义 ChunkIndexStatus 枚举。知识块的索引状态由其在 Milvus/BM25 索引中的存在性隐式表达——`active` 知识块存在于索引中，`deleted` 知识块从索引中移除。索引操作的成功/失败直接反映在 Document 级别的 `status` 和 `error_message` 上。

#### Scenario: 知识块索引成功
- **WHEN** 知识块成功写入 Milvus 和 BM25 索引
- **THEN** 知识块保持 `active` 状态，无需额外的索引状态字段

#### Scenario: 知识块索引失败
- **WHEN** 知识块写入索引时发生异常
- **THEN** 所属 Document 的 `status` SHALL 变更为 `failed`
- **AND** `error_message` SHALL 记录索引失败的详细信息
