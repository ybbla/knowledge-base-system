## Why

当前入库管线在解析根文档后，又通过 `RecursiveLoader` 再次解析同一个根文档，导致根文档的 ParsedElement 被重复送入语义抽取和索引链路。阶段 4 XLSX 入库已经接近闭环，若不先收敛这个问题，表格、标题和资源引用会在知识块生成时被重复消费。

同时，API 合约测试中的上传用例会受当前 `.env` 的 `MINIO_ENABLED` 影响：当本地环境启用 MinIO 时，本应验证本地写入的测试会走 MinIO 分支，造成非确定性失败。需要让测试显式隔离存储后端状态。

## What Changes

- 调整入库管线与递归加载器的协作方式，确保根文档只解析一次，递归加载仅补充嵌入文档产生的 Document 和 ParsedElement。
- 保留递归嵌入文档的深度限制、去重和元素数量边界语义，不改变对外 `/ingest` API。
- 增加或调整测试，验证入库管线不会向语义抽取层传递重复的根文档元素。
- 稳定 `/upload` API 合约测试，使本地上传用例显式运行在 MinIO 未启用场景，MinIO 回退用例显式运行在 MinIO 启用但不可用场景。
- 不新增公共 API，不改变存储后端配置项，不改变 MinIO 生产行为。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `document-ingestion`：明确根文档在一次入库任务中只应解析并提交一次，递归加载不应重复返回根文档元素。
- `file-upload`：明确上传接口测试和本地回退验证应隔离运行时 MinIO 环境，保证本地写入和 MinIO 回退场景可重复验证。

## Impact

- 受影响代码：
  - `knowledge_base_system/ingestion/pipeline.py`
  - `knowledge_base_system/ingestion/recursive_loader.py`
  - `knowledge_base_system/tests/test_ingestion_xlsx.py`
  - `knowledge_base_system/tests/test_markdown_ingest.py` 或新增/调整入库管线测试
  - `knowledge_base_system/tests/test_api_contracts.py`
- 公共 API：无变化，`/upload` 和 `/ingest` 请求/响应结构保持向后兼容。
- 数据影响：修复后新入库任务不会再重复消费根文档元素；已有重复生成的知识块需要按现有删除或重建流程处理。
- 依赖影响：无新增依赖。
- 对现有功能的影响：Markdown/TXT/DOCX/XLSX 入库仍通过 ParserRegistry 分派；MinIO 启用时上传仍写入 MinIO，未启用或失败时仍回退本地。

回滚计划：

- 若修复影响递归嵌入文档，可恢复入库管线中原有的 `RecursiveLoader.load()` 合并逻辑，并临时接受根元素重复风险。
- 若测试隔离调整造成兼容问题，可先仅在测试中 monkeypatch `get_settings`，不改上传实现。
- 回滚不需要数据迁移；只会影响后续入库任务的元素消费方式。
