## Why

当前语义抽取将文档按 h2 标题切分为多个窗口，每个窗口独立调用 LLM。窗口之间 LLM 彼此看不见，导致跨窗口上下文丢失、语义边界决策只能基于局部信息。1M 上下文的模型已普及——经实测估算，95% 以上的实际文档全文 JSON 输入在 50K~80K tokens，仅 1M 窗口的 5%~8%。窗口策略的"上下文约束"前提已不再成立，其代价（窗口边界语义断裂、代码复杂度、跨章节信息丢失）已成为不必要的负担。

## What Changes

- 语义抽取从"窗口循环"改为"全文一次调用"，LLM 接收完整文档元素 JSON，自行决定知识块边界
- 删除 `SemanticExtractor` 中的窗口切分方法（`_build_windows`、`_split_section`、`_estimate_tokens`）
- `extract()` 方法直接调用一次 LLM，返回全部 chunk，不再有循环
- 保留 `_build_windows` 核心逻辑作为溢出保护：仅当元素总量超过安全阈值（800K tokens）时触发
- 增强语义抽取 system prompt：新增知识块切分原则，引导 LLM 在全文档范围内做出合理的边界决策
- 移除 `ingest_job_id` 和 `doc_version` 幽灵参数
- 从 AssetRelation prompt 枚举中移除预留值 `source` 和 `attachment`

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `semantic-extraction`: 窗口切分从"主路径"变为"溢出保护"；LLM 从逐窗口独立调用变为全文单次调用；prompt 增加全文档切分原则；KnowledgeChunk 构造移除无效字段；AssetRelation prompt 精简

## Impact

- **代码**：[`semantic_extractor.py`](knowledge_base_system/llm/semantic_extractor.py)（核心变更，~150 行删除，~80 行新增）、[`prompts.py`](knowledge_base_system/llm/prompts.py)（prompt 增强）、[`pipeline.py`](knowledge_base_system/ingestion/pipeline.py)（调用签名对齐）
- **API**：无变更
- **数据模型**：无变更（仅移除无效传参）
- **运行时行为**：
  - 小/中型文档（≤95%场景）：1 次 LLM 调用替代原来的 N 次，chunk 质量因全局上下文提升
  - 极端大文档：触发溢出保护，回退到窗口模式，行为与当前一致
- **回滚**：恢复 `_build_windows` 作为主路径，或在调用方回退到上一个 git commit
