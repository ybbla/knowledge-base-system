# Semantic Extraction

## Purpose

将 ParsedElement 窗口输入 LLM，生成独立可读的 KnowledgeChunk，包含内容、标题、知识类型、业务分类、资源引用和来源引用。KnowledgeChunk 新增 `category` 字段，从所属 Document 继承。

> 同步自 change `align-data-model-and-api-with-updated-design`。

## MODIFIED Requirements

### Requirement: KnowledgeChunk 持久化存储并保留溯源信息

系统 SHALL 存储生成的 KnowledgeChunk，包含完整的来源引用、资源关联和业务分类。

#### Scenario: 知识块存储时包含来源和资源引用

- **WHEN** LLM 返回一个有效的 chunk
- **THEN** 创建 KnowledgeChunk 记录，包含 `chunk_id`、`doc_id`、`doc_version`、`title`、`content`、`content_hash`、`knowledge_type`、`category`、`status="active"`、`asset_refs`、`source_refs`、`ingest_job_id` 和 `metadata.title_path`
- **AND** `category` 从所属 Document 的 `category` 继承
- **AND** 每个 `source_refs` 条目补齐 `doc_id`、`doc_version`、`element_id` 和 `source_location`
