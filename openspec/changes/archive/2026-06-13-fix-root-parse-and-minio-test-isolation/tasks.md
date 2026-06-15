## 1. 入库重复解析定位与测试

- [x] 1.1 增加入库管线测试，构造不含嵌入文档的 XLSX 或 Markdown 文档，断言语义抽取层收到的根 ParsedElement 不重复。
- [x] 1.2 增加入库管线测试，构造包含 `embedded_doc_id` 的根元素，断言根元素只出现一次且嵌入文档元素仍会追加。
- [x] 1.3 检查现有 `test_ingestion_xlsx.py`，补充对 extractor 接收元素数量和类型顺序的断言，防止阶段 4 表格被重复消费。

## 2. 递归加载器协作调整

- [x] 2.1 在 `RecursiveLoader` 中保留现有 `load()` 入口，并新增或调整一个从已解析根元素继续递归嵌入文档的明确入口。
- [x] 2.2 调整 `IngestionPipeline._run()`，使用首次 `parser.parse(doc)` 的结果作为根文档唯一解析结果，只将递归加载返回的子文档和子元素追加到根元素后。
- [x] 2.3 确认 `max_depth`、重复 `source_hash` 跳过和 `max_elements_per_doc` 统计在新入口下仍按预期生效。
- [x] 2.4 确认根文档 assets 仍经过 `_prepare_assets()`，且嵌入文档处理不改变现有资源生命周期行为。

## 3. API 合约测试隔离

- [x] 3.1 调整 `test_upload_defaults_and_writes_file`，显式 monkeypatch `upload_api.get_settings` 返回 `minio_enabled=False`。
- [x] 3.2 保留并收紧 MinIO 回退测试，显式 monkeypatch `upload_api.get_settings` 返回 `minio_enabled=True`，并使用失败的 MinIO store 验证本地回退。
- [x] 3.3 确认上传测试不依赖开发者本机 `.env`、MinIO 服务状态或全局环境变量。

## 4. 回归验证

- [x] 4.1 在 `D:\xueyy\develop\knowledge-base-system\knowledge_base_system` 下运行阶段 4 相关测试：`python -m pytest tests/test_xlsx_parser.py tests/test_ingestion_xlsx.py tests/test_parser_registry.py -q`。
- [x] 4.2 在 `D:\xueyy\develop\knowledge-base-system\knowledge_base_system` 下运行入库与 API 合约回归：`python -m pytest tests/test_api_contracts.py tests/test_markdown_ingest.py tests/test_docx_parser.py -q`。
- [x] 4.3 如本机 shell 工作目录仍异常，使用显式 `PYTHONPATH=D:\xueyy\develop\knowledge-base-system\knowledge_base_system` 和绝对测试路径重新验证。
- [x] 4.4 运行 `openspec validate fix-root-parse-and-minio-test-isolation`，确认 proposal、design、specs 和 tasks 可通过校验。
