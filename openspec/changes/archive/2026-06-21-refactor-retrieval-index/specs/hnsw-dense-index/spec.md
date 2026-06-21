# HNSW Dense Index

## Purpose

将 Milvus dense 向量索引从 IVF_FLAT 升级为 HNSW（分层可导航小世界图），提供更高的召回率和更稳定的查询性能。

## ADDED Requirements

### Requirement: HNSW 索引替代 IVF_FLAT

系统 SHALL 对 `dense_vector` 字段使用 HNSW 索引类型 + COSINE 距离度量，替代原有的 IVF_FLAT（nlist=128）。

#### Scenario: 创建 Collection 时使用 HNSW 索引
- **WHEN** Milvus Collection 首次创建
- **THEN** `dense_vector` 索引参数为 `{"index_type": "HNSW", "metric_type": "COSINE", "params": {"M": 16, "efConstruction": 200}}`
- **AND** 索引类型和参数均可通过配置修改

#### Scenario: 向量检索使用 ef 查询参数
- **WHEN** 执行 dense 向量检索
- **THEN** search param 为 `{"metric_type": "COSINE", "params": {"ef": 64}}`
- **AND** ef 值可通过 `MILVUS_HNSW_EF` 环境变量配置

#### Scenario: HNSW 参数可配置
- **WHEN** 管理员修改 `MILVUS_HNSW_M`、`MILVUS_HNSW_EF_CONSTRUCTION` 或 `MILVUS_HNSW_EF` 环境变量
- **THEN** 下次 Collection 重建时使用新参数值

### Requirement: HNSW 索引性能与召回率

系统 SHALL 在 HNSW 索引下保持不低于 IVF_FLAT 的召回率，同时提供更快的查询速度。

#### Scenario: HNSW 召回率不劣于 IVF_FLAT
- **WHEN** 以相同查询向量在 HNSW 和 IVF_FLAT 索引上检索 top_k=50
- **THEN** HNSW 返回的 chunk_id 集合应包含 IVF_FLAT 返回的至少 95% 的结果（召回率 ≥ 95%）

#### Scenario: HNSW 查询延迟可接受
- **WHEN** 执行单次 dense 向量检索
- **THEN** HNSW 查询延迟应不高于 IVF_FLAT 查询延迟的 1.5 倍
