## Context

当前 `IngestionPipeline._run()` 会先通过 ParserRegistry 选择解析器并执行 `parser.parse(doc)`，随后又创建 `RecursiveLoader(parser_fn=parser.parse)` 并调用 `loader.load(doc, effective_raw)`。`RecursiveLoader.load()` 的现有语义是“解析 root doc 并递归解析所有 embedded docs”，因此根文档会被解析两次，`elements.extend(all_elements)` 会把重复的根元素送入 `SemanticExtractor.extract()`。

这个问题在阶段 4 XLSX 入库中更明显：一个简单工作簿首次解析会产生工作表标题和表格元素，递归加载器再次解析同一工作簿后会产生另一组等价元素，导致表格内容被重复转写和索引。

上传 API 合约测试还有一个环境耦合点：`upload_file()` 运行时通过 `get_settings(reload_env=True)` 读取 `.env` 或环境变量。当本机启用 `MINIO_ENABLED=true` 时，默认上传测试会返回 `minio://`，而测试断言期望本地 `file://data/uploads/`，导致同一测试在不同开发环境下结果不稳定。

受影响模块：

- `knowledge_base_system/ingestion/pipeline.py`
- `knowledge_base_system/ingestion/recursive_loader.py`
- `knowledge_base_system/tests/test_ingestion_xlsx.py`
- `knowledge_base_system/tests/test_markdown_ingest.py` 或新增入库管线测试
- `knowledge_base_system/tests/test_api_contracts.py`
- OpenSpec delta specs：`document-ingestion`、`file-upload`

## Goals / Non-Goals

**Goals:**

- 确保一次入库任务中根文档只解析一次，语义抽取层不会收到重复的根文档 ParsedElement。
- 保持嵌入文档递归解析能力，包括最大深度、重复文档跳过和元素数量边界。
- 保持 `/ingest`、`/upload` 公共 API 和运行时配置项不变。
- 让上传 API 合约测试显式覆盖“MinIO 未启用时本地写入”和“MinIO 启用但不可用时本地回退”，不受开发者 `.env` 影响。

**Non-Goals:**

- 不重写递归加载器为跨格式资源调度系统。
- 不新增 `source_type` 自动推断。
- 不改变 MinIO 上传路径、bucket 命名或 presigned URL 行为。
- 不处理历史已生成的重复知识块；历史数据仍通过现有删除或重建流程修复。

## Decisions

### 1. 根文档由 IngestionPipeline 解析，RecursiveLoader 只补充嵌入文档

选择：保留 `IngestionPipeline` 中首次 `parser.parse(doc)` 作为根文档的唯一解析入口。递归加载阶段应复用首次解析得到的根元素来发现 `embedded_doc_id`，并只递归解析子文档，返回额外的子 Document 和子 ParsedElement。

理由：

- 入库管线需要在根文档解析后立即准备 assets、持久化 elements，并把同一组元素传给语义抽取；根解析作为单一事实来源更清晰。
- 避免让解析器为了幂等性承担重复解析去重责任，尤其 XLSX、DOCX 等二进制格式解析成本更高。
- 对外 API 和解析器接口不变，变更范围收敛在入库编排层。

备选：

- 让 `RecursiveLoader.load()` 继续解析 root，但管线不再提前解析 root。缺点是 assets 处理和 root parse result 的控制点会转移，影响面更大。
- 在 `elements.extend(all_elements)` 前按 `element_id` 或文本去重。缺点是第二次解析会生成不同 `element_id`，文本去重也可能误伤合法重复内容。

### 2. 保持 RecursiveLoader 的边界能力，但补充“从已解析根元素继续递归”的入口

选择：递归加载器可以新增或调整一个内部入口，用已解析的 root elements 发现 embedded docs，并从子文档开始递归。原有深度限制、source_hash 去重、max_elements 统计仍由 RecursiveLoader 维护。

理由：

- 递归边界逻辑仍集中在 `RecursiveLoader`，不会散落到 `IngestionPipeline`。
- 能通过测试直接验证 root elements 不重复，同时继续验证嵌入文档跳过和边界行为。

备选：

- 把嵌入文档递归逻辑全部移到 `IngestionPipeline`。缺点是管线类会膨胀，递归边界更难单测。

### 3. API 合约测试显式注入上传配置

选择：在上传 API 合约测试中 monkeypatch `upload_api.get_settings`，让默认本地上传测试固定返回 `minio_enabled=False`，让 MinIO 回退测试固定返回 `minio_enabled=True` 且使用失败的 MinIO store。

理由：

- 测试意图与运行时环境解耦，避免 `.env`、本地 MinIO 服务状态或 CI 环境变量影响断言。
- 不改变生产代码，只收稳测试边界。

备选：

- 在测试命令前统一设置 `MINIO_ENABLED=false`。缺点是隐藏了测试自身对环境的依赖，单测文件被单独运行时仍可能失败。

## Risks / Trade-offs

- [嵌入文档递归遗漏] 如果递归加载器只从子文档开始，可能漏掉根元素中的 embedded document 发现逻辑。→ 使用已解析根元素作为递归入口输入，并补充覆盖嵌入文档的测试。
- [元素数量统计语义变化] 原先重复解析会把根元素计入两次，修复后计数会下降。→ 这是目标行为；测试应断言语义抽取层收到的根元素数量等于首次解析数量。
- [历史知识块仍重复] 修复只影响新入库任务。→ 在说明中保留重建建议，不自动迁移历史数据。
- [测试过度 mock] 上传测试 monkeypatch 配置后可能脱离真实启动配置。→ 保留 MinIO 回退路径测试，并让生产配置读取逻辑不变。

## Migration Plan

1. 调整入库管线和递归加载器协作，确保根文档只解析一次。
2. 补充 XLSX 或通用入库管线测试，断言语义抽取层收到的元素不重复。
3. 补充或调整递归加载器测试，确保嵌入文档仍按深度和去重规则处理。
4. 调整 API 合约测试的上传配置隔离。
5. 运行阶段 4 XLSX 相关测试和入库/API 合约回归测试。

回滚策略：

- 恢复 `IngestionPipeline` 调用 `RecursiveLoader.load()` 后直接 `elements.extend(all_elements)` 的旧逻辑。
- 保留测试配置隔离也可独立存在；若需完全回滚，可恢复上传测试依赖环境变量的原状。

## Open Questions

- 是否保留 `RecursiveLoader.load()` 的旧语义作为兼容入口，并新增一个更明确的方法处理“已解析根元素”？建议保留旧入口，新增更明确的方法，降低对现有测试和调用点的冲击。
- 是否需要在本变更中补充历史重复知识块检测脚本？建议不纳入，本次只修新入库路径。
