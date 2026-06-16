# Semantic Extraction（Delta）

## Purpose

语义抽取窗口注入资源视觉描述。当 Asset 具有 `extracted_text`（图片或视频的多模态模型描述）时，系统在构造 LLM 输入窗口时将这些描述注入，使 LLM 能够将图片和视频的语义自然融合到知识块正文中。

> 修改自 change `phase-5-multimodal-enhancement`，日期 2026-06-15。

## ADDED Requirements

### Requirement: Asset 视觉描述注入 LLM 窗口

系统 SHALL 在构造 LLM 语义抽取窗口时，将窗口中元素关联的 Asset 的 `extracted_text` 作为资源描述注入输入 JSON。

#### Scenario: 图片有视觉描述时注入窗口

- **GIVEN** 窗口包含一个 `element_type=image` 的元素，其关联 Asset 的 `extracted_text` 为 "图片展示了用户上传文档后的解析状态列表，包括处理中、成功和失败三种状态"
- **WHEN** 系统调用 `_elements_to_json()` 序列化窗口
- **THEN** 生成的 JSON 中该元素节点包含 `asset_descriptions` 字段
- **AND** `asset_descriptions` 包含该 Asset 的 `asset_id`、`asset_type` 和 `description`（即为 `extracted_text` 的值）

#### Scenario: 图片无视觉描述时不注入

- **GIVEN** 窗口包含一个 `element_type=image` 的元素，其关联 Asset 的 `extracted_text` 为 `None`
- **WHEN** 系统构造 LLM 输入窗口
- **THEN** 该元素的 `asset_descriptions` 为空数组或不包含该 Asset 的描述

#### Scenario: 多个资源描述同时注入

- **GIVEN** 窗口包含一个段落元素，其关联了两个图片 Asset，且两个 Asset 均有 `extracted_text`
- **WHEN** 系统构造 LLM 输入
- **THEN** `asset_descriptions` 包含两个资源的描述
- **AND** LLM prompt 中明确要求将资源描述内容自然融合到知识块正文

#### Scenario: 视频有语义描述时注入窗口

- **GIVEN** 窗口包含一个 `element_type=video` 的元素，其关联 Asset 的 `extracted_text` 为视频内容总结
- **WHEN** 系统构造 LLM 输入
- **THEN** 视频的 `extracted_text` 通过 `asset_descriptions` 注入窗口
- **AND** LLM 在生成知识块时自然融合视频总结内容

#### Scenario: 语义抽取 prompt 更新

- **WHEN** 系统调用 `build_extraction_messages()` 构造 LLM 请求
- **THEN** system prompt 包含指令：若窗口包含 `asset_descriptions`，则将其中的资源描述内容自然融合到对应知识块的正文中
- **AND** prompt 不要求 LLM 编造资源描述中没有的信息
