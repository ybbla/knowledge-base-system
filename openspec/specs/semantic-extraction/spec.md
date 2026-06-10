# Semantic Extraction

## Purpose

将 ParsedElement 窗口输入 LLM，生成独立可读的 KnowledgeChunk，包含内容、标题、知识类型、业务分类、资源引用和来源引用。KnowledgeChunk 新增 `category` 字段，从所属 Document 继承。

`knowledge_type` 字段分为三类（`declarative` 陈述型 / `relational` 关系型 / `procedural` 流程型），LLM 在生成时即根据内容特征分类标注；当前下游检索链路对所有类型按陈述型统一处理，后续启用差异化策略时无需重新入库。

> 同步自 change `implement-mvp-phase-1`，日期 2026-06-09；更新自 change `align-data-model-and-api-with-updated-design`，日期 2026-06-10。

## Requirements

### Requirement: LLM 输入前将 ParsedElement 整理为结构窗口

系统 SHALL 优先保持解析结构完整；当文档超过上下文、成本过高或结构复杂时，将 ParsedElement 按 h2 或更高层级标题边界分组为结构窗口，窗口大小由 `max_window_tokens` 配置控制。

#### Scenario: 单个章节放入一个窗口

- **WHEN** 一个 h2 标题下的章节包含 5 个元素，共约 500 token
- **THEN** 所有 5 个元素组成一个窗口

#### Scenario: 大章节在段落边界拆分

- **WHEN** 一个章节的元素总计超过 `max_window_tokens`
- **THEN** 系统在段落、表格或资源边界处拆分为多个窗口，每个窗口保留标题路径并与前一窗口重叠末尾关键元素

#### Scenario: 窗口包含标题路径和来源位置

- **WHEN** 构建窗口时
- **THEN** LLM 的输入包含当前 `section_path`、每个元素的 `element_type`/`text`/`structured_data`、`source_location` 以及关联 Asset 的 `asset_id`、`asset_type`、`caption` 或 `extracted_text`

#### Scenario: 嵌入文档不在父窗口展开

- **WHEN** 窗口包含 `embedded_document` 元素
- **THEN** 父窗口只包含 `embedded_doc_id` 和嵌入文档标题
- **AND** 子文档通过独立递归解析生成自己的 KnowledgeChunk

### Requirement: LLM 从窗口生成 KnowledgeChunk

系统 SHALL 将每个窗口输入 LLM，接收包含一个或多个 KnowledgeChunk 的结构化 JSON 输出。

#### Scenario: 段落和表格合并为单个知识块

- **WHEN** 窗口包含关于文档上传的段落和上传状态的表格
- **THEN** LLM 返回一个 chunk，其 `content` 融合了段落文本和表格的自然语言描述，根据内容特征标注 `knowledge_type`（`declarative` / `relational` / `procedural`），`source_refs` 引用两个元素

#### Scenario: 含图片的表格单元格

- **WHEN** 表格单元格包含有 `extracted_text` 的图片
- **THEN** LLM 输出的 `content` 自然地将图片语义描述融入单元格文本

#### Scenario: 图片仅作为证据

- **WHEN** 窗口包含文本和一张辅助说明的截图
- **THEN** LLM 生成一个 chunk，`content` 自然提及图片，`asset_refs` 包含图片的 asset_id、关系、关联文本、caption 和渲染指令

#### Scenario: LLM 按内容分类标注 knowledge_type

- **WHEN** LLM 生成 KnowledgeChunk 时
- **THEN** 每个 chunk 的 `knowledge_type` 根据内容特征标注为 `declarative`（事实陈述/定义说明）、`relational`（实体关联/依赖关系）或 `procedural`（操作步骤/流程）
- **AND** 当前下游检索链路对所有类型统一按陈述型处理，后续启用差异化策略时已有标注基础

#### Scenario: LLM 输出 JSON 校验失败

- **WHEN** LLM 返回格式错误的 JSON 或未通过 schema 校验的 JSON
- **THEN** 系统最多重试 3 次，全部失败后将该窗口标记为失败并记录错误

#### Scenario: LLM 不编造内容

- **WHEN** 窗口引用了一个没有 `extracted_text` 的视频
- **THEN** LLM 输出不得描述具体视频内容，只能标注存在一个视频资源

### Requirement: KnowledgeChunk 持久化存储并保留溯源信息

系统 SHALL 存储生成的 KnowledgeChunk，包含完整的来源引用、资源关联和业务分类。

#### Scenario: 知识块存储时包含来源和资源引用

- **WHEN** LLM 返回一个有效的 chunk
- **THEN** 创建 KnowledgeChunk 记录，包含 `chunk_id`、`doc_id`、`doc_version`、`title`、`content`、`content_hash`、`knowledge_type`、`category`、`status="active"`、`asset_refs`、`source_refs`、`ingest_job_id` 和 `metadata.title_path`
- **AND** `category` 从所属 Document 的 `category` 继承
- **AND** 每个 `source_refs` 条目补齐 `doc_id`、`doc_version`、`element_id` 和 `source_location`
