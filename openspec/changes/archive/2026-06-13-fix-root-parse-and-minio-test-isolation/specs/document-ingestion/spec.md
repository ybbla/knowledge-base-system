## MODIFIED Requirements

### Requirement: 处理递归嵌入文档并设置边界

系统 SHALL 递归解析嵌入文档至可配置的最大深度，并支持去重。系统 MUST 在一次入库任务中只解析并提交一次根文档元素；递归加载只能补充嵌入文档产生的 Document 和 ParsedElement，不得重复返回根文档 ParsedElement。

#### Scenario: 根文档只解析一次

- **GIVEN** 文档 A 不包含嵌入文档
- **WHEN** 提交文档 A 入库
- **THEN** 语义抽取层只接收文档 A 首次解析产生的 ParsedElement
- **AND** 文档 A 的标题、段落、表格或资源元素不得因递归加载重复出现

#### Scenario: 根文档包含嵌入文档时不重复根元素

- **GIVEN** 文档 A 包含嵌入文档 B
- **WHEN** 提交文档 A 入库
- **THEN** 语义抽取层接收文档 A 的 ParsedElement 一次
- **AND** 系统继续递归解析文档 B 并追加文档 B 的 ParsedElement
- **AND** 文档 A 的 ParsedElement 不因发现文档 B 被再次解析或再次追加

#### Scenario: 深度限制内递归解析

- **GIVEN** 文档 A 嵌入文档 B，文档 B 嵌入文档 C，max_depth=3
- **WHEN** 提交文档 A 入库
- **THEN** 三个文档全部被解析，每个 Document 的 `parent_doc_id` 和 `root_doc_id` 正确指向文档 A

#### Scenario: 超出最大深度

- **GIVEN** 文档 A 在深度 3 处嵌入文档 B，max_depth=3
- **WHEN** 提交文档 A 入库
- **THEN** 文档 B 不被递归解析，其 Document 记录标记 `metadata.skipped_reason="max_depth_exceeded"`

#### Scenario: 重复文档跳过

- **GIVEN** 同一文档（相同 `source_hash`）在递归链路中遇到两次
- **WHEN** 提交根文档入库
- **THEN** 重复文档被跳过，标记 `metadata.skipped_reason="duplicated_document"`

#### Scenario: 外部资源阶段 1 仅识别关联

- **GIVEN** 文档包含图片、视频或附件链接
- **WHEN** 提交文档入库
- **THEN** 系统创建 Asset 并与 ParsedElement 关联
- **AND** 阶段 1 不要求下载到 MinIO、不要求生成 `storage_uri`，后续资源处理可异步补齐
