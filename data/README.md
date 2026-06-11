# 数据目录说明

- `source_documents/`：人工放入的原始业务资料，用于批量入库或构建知识库。
- `uploads/`：服务运行时由 `/upload` 端点写入的上传文件。
- `runtime/`：预留给后续索引快照、缓存或本地运行状态。

测试样例不放在这里，统一放在 `knowledge_base_system/tests/fixtures/`。
