# Semantic Extraction Delta

## REMOVED Requirements

### Requirement: 嵌入文档不在父窗口展开

**Reason**: `embedded_document` 元素类型不再使用。子文档通过 `document_link` Asset 独立走完整入库流程，LLM 语义抽取窗口不再需要处理嵌入文档元素。
**Migration**: 无需迁移。语义抽取输入中不再出现 `embedded_document` 元素。
