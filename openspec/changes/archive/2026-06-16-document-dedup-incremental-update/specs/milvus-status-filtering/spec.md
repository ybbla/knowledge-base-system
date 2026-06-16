## ADDED Requirements

### Requirement: Milvus Collection Schema 包含 status 字段

Milvus Collection 的 Schema SHALL 包含 `status` 字段（类型 VARCHAR，默认值 `"active"`），用于在索引层过滤非活跃知识块。

#### Scenario: 新写入的知识块默认 status 为 active
- **WHEN** 新的 `KnowledgeChunk` 被写入 Milvus
- **THEN** 其实体的 `status` 字段值为 `"active"`

#### Scenario: 旧知识块 status 更新为 superseded
- **WHEN** 文档更新完成后旧知识块需要在索引层淘汰
- **THEN** 系统 upsert 对应实体的 `status` 为 `"superseded"`，保留向量和元数据不变

### Requirement: 检索时自动过滤非 active 知识块

所有 Milvus 检索操作（dense vector search、sparse vector search、hybrid search）SHALL 在搜索表达式（expr）中叠加 `status == "active"` 过滤条件，确保不返回已淘汰的知识块。

#### Scenario: 向量检索只返回 active 知识块
- **WHEN** 执行 `VectorIndex.search()` 查询
- **THEN** Milvus search expr 包含 `status == "active"` 条件

#### Scenario: 混合检索只返回 active 知识块
- **WHEN** 执行 `hybrid_search()` 调用
- **THEN** 所有 AnnSearchRequest 的 expr 包含 `status == "active"` 条件

#### Scenario: 按 category 过滤时叠加 status 条件
- **WHEN** 检索请求指定 `category = "产品使用"`
- **THEN** Milvus expr 为 `(category == "产品使用") && (status == "active")`

### Requirement: Milvus Collection 重建后自动恢复索引

当 Milvus Collection 因 Schema 变更需要重建时，系统 SHALL 在启动时通过 `rebuild_retrieval_indexes_from_chunks` 从 PostgreSQL 中的 `status='active'` 知识块全量重建索引。

#### Scenario: 启动时恢复索引
- **WHEN** 应用启动且 Milvus Collection 为空或不存在
- **THEN** `startup_resources()` 从 PostgreSQL 读取所有 `status='active'` 的 knowledge chunks 并重新写入 Milvus
