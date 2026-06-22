## 1. 上传接口改造

- [x] 1.1 `upload_document()` 中 `_hash_upload()` 替换为 `file.file.read()` + `compute_hash()`，保留 `file_content`
- [x] 1.2 `ingestion_pipeline.ingest(doc)` 改为 `ingestion_pipeline.ingest(doc, raw_content=file_content)`

## 2. Pipeline 改造

- [x] 2.1 `ingest()` 签名增加 `raw_content: bytes | str | None = None` 参数
- [x] 2.2 `_run_create()` 签名增加 `raw_content` 参数
- [x] 2.3 实现降级路径：`raw_content` 为 None 时从 MinIO / `file://` 读取，根据 `parser.CONTENT_IS_TEXT` 决定 decode
- [x] 2.4 删除 `RAW_CONTENT_FORMAT` 相关代码（已无此属性）
- [x] 2.5 `parser.parse(doc)` 改为 `parser.parse(doc, raw_content)`

## 3. Parser 基类改造

- [x] 3.1 `DocumentParser.parse()` 签名改为 `parse(self, doc: Document, content: bytes | str) -> ParseResult`
- [x] 3.2 新增 `CONTENT_IS_TEXT: bool = False` 类属性（仅降级路径使用）
- [x] 3.3 删除 `_read_content()`、`_normalize_raw()`、`_cleanup_raw_content()`、`RAW_CONTENT_FORMAT`

## 4. 六个解析器适配

- [x] 4.1 `MarkdownParser`：签名改为 `(self, doc, content)`，设 `CONTENT_IS_TEXT = True`，删除 `_read_content()` 调用
- [x] 4.2 `HtmlParser`：同上
- [x] 4.3 `DocxParser`：签名改为 `(self, doc, content)`，删除 `_read_content()` 调用
- [x] 4.4 `PdfParser`：同上
- [x] 4.5 `PptxParser`：同上
- [x] 4.6 `XlsxParser`：同上

## 5. 其余调用点适配

- [x] 5.1 `documents.py:275` 的 `ingest(created)` 确认走降级路径，无需改签名
- [x] 5.2 `documents.py:659/663/707` 的 `ingest(doc)` 确认走降级路径，无需改签名
- [x] 5.3 `RecursiveLoader` 中 `parser.parse(sub_doc)` 改为 `parser.parse(sub_doc, content)`，内容从 source_uri/metadata 读取

## 6. 测试更新

- [x] 6.1 `test_parser_registry.py`：fake parser 的 `parse()` 签名改为 `(self, doc, content)`
- [x] 6.2 删除 `test_parser_registry.py` 中 `RAW_CONTENT_FORMAT` 和 `_cleanup_raw_content` 相关测试，替换为 `CONTENT_IS_TEXT` 测试
- [x] 6.3 `test_ingestion_*.py`：所有 `parser.parse(doc)` 改为 `parser.parse(doc, content)`
- [x] 6.4 `test_ingestion_with_milvus_minio.py`：`ingest(doc)` 确认走降级路径

## 7. 全量验证

- [x] 7.1 运行 `pytest` 确认无回归（43/43 通过 — parser 测试全部通过）
- [ ] 7.2 启动后端，通过 Playwright 验证上传→解析→检索完整链路（需 Docker 环境）
