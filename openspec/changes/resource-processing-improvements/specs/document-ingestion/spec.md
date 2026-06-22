# Document Ingestion Delta

## REMOVED Requirements

### Requirement: 处理递归嵌入文档并设置边界

**Reason**: `RecursiveLoader` 创建的子 Document `source_uri=""` 导致解析器无法获取内容，实际不可用。子文档处理由 `document_link` Asset 的完整入库流程替代（HTTP下载→MinIO上传→创建子Document→ingest）。
**Migration**: Markdown `[[link]]` 改为创建 `document_link` Asset。不再有递归概念，子文档就是子文档，走和用户上传相同的入库流水线。

## MODIFIED Requirements

### Requirement: 解析嵌入文档链接

系统 SHALL 在解析阶段识别文档链接，创建 `document_link` 类型的 Asset，由资源处理管线统一下载并触发子文档入库。

#### Scenario: 解析嵌入文档链接
- **WHEN** Markdown 文档包含指向其他文档的链接 `[子文档](https://example.com/child.md)`
- **THEN** 解析器创建 `document_link` Asset（`original_uri` 为链接 URL，`asset_type=document_link`）
- **AND** 不再设置 `embedded_doc_id`
