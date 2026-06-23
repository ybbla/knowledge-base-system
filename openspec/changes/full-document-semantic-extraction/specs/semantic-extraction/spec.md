## MODIFIED Requirements

### Requirement: LLM 输入前将 ParsedElement 整理为结构窗口

系统 SHALL 优先将文档的全部 ParsedElement 作为单次输入传入 LLM。仅当全文 token 估算超过安全阈值（模型上下文窗口 × 0.8），或全文 LLM 调用失败时，系统 SHALL 按标题层级递进切分：先按 heading_level=1 切分，仅对其中仍超限的 section 按 heading_level=2 再切，以此类推。最深层级仍超限或无标题可切时，SHALL 依次尝试 embedding 语义断点切分和 token 硬切兜底。

#### Scenario: 常规文档全文一次调用

- **WHEN** 文档的元素序列化后估算 token 数不超过安全阈值
- **THEN** 系统将所有元素序列化为一个 JSON 数组并一次性提交给 LLM
- **AND** LLM 从全文元素中自行判断知识块边界

#### Scenario: 全文超限时按 h1 切分

- **GIVEN** 文档的元素序列化后估算 token 数超过安全阈值，且文档包含 heading_level=1 的标题
- **WHEN** 系统进入降级路径
- **THEN** 系统在 heading_level=1 处切分，每个 h1 section 独立处理
- **AND** 未超限的 h1 section 完整提交给 LLM

#### Scenario: 超限 section 递归按更深层级切分

- **GIVEN** 一个 h1 section 的 token 估算仍超过安全阈值，且该 section 包含 heading_level=2 的标题
- **WHEN** 系统处理该 section
- **THEN** 系统在其 heading_level=2 处再切分
- **AND** 对仍超限的 h2 subsection 继续按 h3 切分，以此类推
- **AND** 未超限的兄弟 section 保持完整，不参与更深层切分

#### Scenario: 标题耗尽后按 embedding 语义断点切分

- **GIVEN** 一个 section 的 token 估算超过安全阈值，且已无更深层标题可切，且 embedding 服务可用
- **WHEN** 系统处理该 section
- **THEN** 系统计算相邻元素的 embedding 相似度，在相似度陡降处切分
- **AND** 切出的每个子 section 独立提交 LLM

#### Scenario: embedding 切分后仍超限触发 token 硬切

- **GIVEN** 一个 section 已通过 embedding 相似度切分，但切出的子 section 仍有个别超过安全阈值
- **WHEN** 系统处理该子 section
- **THEN** 系统在该子 section 上执行 token 硬切（段落边界 + 20% 重叠）
- **AND** embedding 只负责选切分点，不保证切后不超限

#### Scenario: embedding 不可用时的 token 硬切兜底

- **GIVEN** 一个 section 超限、无标题、且 embedding 服务不可用
- **WHEN** 系统处理该 section
- **THEN** 系统在段落边界按 token 上限硬切，每个子窗口重叠末尾 20% 的元素

#### Scenario: 全文 LLM 调用失败降级

- **WHEN** 全文 LLM 调用抛出异常（API 超时、服务端错误、JSON 解析失败重试耗尽）
- **THEN** 系统进入降级路径，复用与超限相同的标题递进切分策略
- **AND** 对切分后的每个 section 独立调用 LLM

#### Scenario: 全文 LLM 返回空结果降级

- **WHEN** 全文 LLM 调用成功但返回的 `chunks` 为空或所有 chunk 的 `content` 为空
- **THEN** 系统视为失败，进入降级路径

#### Scenario: section 级 LLM 失败继续降级

- **GIVEN** 降级路径中某个 section 的 LLM 调用失败
- **WHEN** 该 section 仍有更深层标题可切
- **THEN** 系统在该 section 上按更深层标题再切分
- **AND** 递归重试每个子 section
- **AND** 若已无更深层标题 → `_fallback_chunks` 纯文本拼接兜底

#### Scenario: 无标题文档超限

- **GIVEN** 文档无任何标题元素且全文 token 估算超限
- **WHEN** 系统进入降级路径
- **THEN** 系统直接进入 embedding 语义断点切分或 token 硬切兜底

### Requirement: LLM 从全文元素生成 KnowledgeChunk

系统 SHALL 将输入元素提交 LLM，接收包含一个或多个 KnowledgeChunk 的结构化 JSON 输出。LLM SHALL 根据 prompt 中的切分原则自行决定知识块边界。

#### Scenario: 段落和表格合并为单个知识块

- **WHEN** 输入包含关于同一主题的段落和表格，且 prompt 切分原则指示同主题内容合并
- **THEN** LLM 返回一个 chunk，其 `content` 融合了段落文本和表格的自然语言描述，根据内容特征标注 `knowledge_type`，`source_refs` 引用相关元素

#### Scenario: 不同主题内容切分为不同知识块

- **WHEN** 输入包含讨论不同主题的多个段落
- **THEN** LLM 根据切分原则将不同主题内容分别归入不同 chunk

#### Scenario: 含图片描述的内容融合

- **WHEN** 元素关联的 Asset 有 `extracted_text`
- **THEN** LLM 输出的 `content` 自然地将资源语义描述融入正文

#### Scenario: LLM 输出 JSON 校验失败

- **WHEN** LLM 返回格式错误的 JSON
- **THEN** 系统最多重试 3 次，全部失败后该 section 进入降级路径

### Requirement: KnowledgeChunk 持久化存储并保留溯源信息

系统 SHALL 存储生成的 KnowledgeChunk，包含完整的来源引用、资源关联和业务分类。

#### Scenario: 知识块存储时包含来源和资源引用

- **WHEN** LLM 返回一个有效的 chunk
- **THEN** 创建 KnowledgeChunk 记录，包含 `chunk_id`、`doc_id`、`title`、`content`、`content_hash`、`knowledge_type`、`category`、`status="active"`、`asset_refs`、`source_refs` 和 `metadata.title_path`
- **AND** `category` 从所属 Document 的 `category` 继承

#### Scenario: LLM 未提供 source_refs 时不强行关联

- **WHEN** LLM 返回的 chunk 没有 `source_refs` 字段
- **THEN** 该 chunk 的 `source_refs` 为空列表
- **AND** 系统不将输入 section 的全部元素作为兜底关联

## ADDED Requirements

### Requirement: 标题递进切分仅作用在超限的 section 上

系统 SHALL 在溢出降级时，仅对 token 估算超限的 section 向下层级递归切分。未超限的兄弟 section SHALL 保持完整，不参与更深层切分。

#### Scenario: 大部分 section 在顶层保持完整

- **GIVEN** 文档包含 10 个 h1 section，其中 8 个各约 30K tokens（未超限），2 个各约 150K tokens（超限）
- **WHEN** 系统按 h1 切分后处理每个 section
- **THEN** 8 个未超限的 h1 section 各自完整提交 LLM
- **AND** 仅 2 个超限的 h1 section 被进一步按 h2 切分

### Requirement: ParsedElement 序列化时注入 heading_level

系统 SHALL 在 `_elements_to_json` 中为标题元素注入 `heading_level` 字段，使 LLM 能区分标题层级。序列化时 SHALL 仅传 `source_location.section_path`，不传 `page` 和 `table_path`。

#### Scenario: 标题元素携带 heading_level

- **GIVEN** 一个 `element_type=title` 的 ParsedElement，其 `metadata.heading_level` 为 2
- **WHEN** 系统序列化该元素
- **THEN** 输出的 JSON 包含 `"heading_level": 2`

#### Scenario: 非标题元素不携带 heading_level

- **GIVEN** 一个 `element_type=paragraph` 的 ParsedElement
- **WHEN** 系统序列化该元素
- **THEN** 输出的 JSON 不包含 `heading_level` 字段

#### Scenario: 代码元素携带 language

- **GIVEN** 一个 `element_type=code` 的 ParsedElement，其 `structured_data.language` 为 `"python"`
- **WHEN** 系统序列化该元素
- **THEN** 输出的 JSON 包含 `"language": "python"`

### Requirement: Token 估算计入结构化数据

系统 SHALL 在估算 token 数时计入 `ParsedElement.structured_data`，采用公式 `len(combined_text) / 1.8` 进行粗略估算。

#### Scenario: 含表格数据的 token 估算

- **GIVEN** 输入包含表格元素，其 `structured_data` 包含大量行数据
- **WHEN** 系统估算 token 数
- **THEN** 估算结果计入 `structured_data` 序列化后的字符数

### Requirement: Prompt 包含 list 和 code 分层处理策略

系统 SHALL 在语义抽取 system prompt 中针对 `list` 和 `code` 元素类型提供分层的处理策略。

#### Scenario: list 步骤类转为自然语言

- **GIVEN** 输入包含步骤/流程类列表（`structured_data.items` 为扁平字符串数组）
- **WHEN** LLM 处理该元素
- **THEN** 根据 prompt 策略将条目转写为连贯的自然语言陈述

#### Scenario: list 嵌套类保留层级

- **GIVEN** 输入包含嵌套列表（`structured_data.items` 含 `children` 字段）
- **WHEN** LLM 处理该元素
- **THEN** 根据 prompt 策略保留层级关系，用缩进或编号标明父子结构

#### Scenario: code 配置类转为自然语言

- **GIVEN** 输入包含 `language` 为 json/yaml/toml 的代码元素
- **WHEN** LLM 处理该元素
- **THEN** 根据 prompt 策略将配置转为自然语言描述

#### Scenario: code 脚本类保留函数签名

- **GIVEN** 输入包含 `language` 为 python/go/java 的代码元素
- **WHEN** LLM 处理该元素
- **THEN** 根据 prompt 策略概括逻辑，保留核心函数签名

### Requirement: KnowledgeChunk 中不包含 relation 字段

系统 SHALL 在 AssetRef 中移除 `relation` 字段，AssetRelation 枚举删除。存量数据中的 `relation` 键在反序列化时丢弃。

#### Scenario: 新建 chunk 的 asset_refs 无 relation

- **WHEN** LLM 返回一个 chunk 或系统构造 fallback chunk
- **THEN** `asset_refs` 条目不包含 `relation` 字段

#### Scenario: 存量数据反序列化不受影响

- **GIVEN** Milvus/PG 中已有 chunk 的 `asset_refs` JSON 包含 `relation` 键
- **WHEN** 系统读取该记录
- **THEN** 反序列化成功，`relation` 键被忽略
