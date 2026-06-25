## MODIFIED Requirements

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
- **AND** asset_data 中不包含 `url` 字段（LLM 无法访问，由检索时从 Asset 表直接查询）

#### Scenario: 嵌入文档不在父窗口展开

- **WHEN** 窗口包含 `embedded_document` 元素
- **THEN** 父窗口只包含 `embedded_doc_id` 和嵌入文档标题
- **AND** 子文档通过独立递归解析生成自己的 KnowledgeChunk

## REMOVED Requirements

（无删除项）
