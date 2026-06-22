## 1. 公共工具模块

- [x] 1.1 创建 `parsers/utils.py`，包含 `MIME_MAP` 和 `guess_mime(url, asset_type)` 函数
- [x] 1.2 定义 `VIDEO_URL_RE`、`HTTP_URL_RE` 正则和 `ATTACHMENT_EXTENSIONS` 常量
- [x] 1.3 实现 `normalize_text(text)` 函数（空白归一化 + HTML 实体解码）
- [x] 1.4 定义 `AssetRecord` dataclass（`asset: Asset`, `key: tuple`）
- [x] 1.5 编写 `tests/test_parser_utils.py`（覆盖 MIME、正则、文本规范化、AssetRecord）

## 2. 基类增强

- [x] 2.1 `DocumentParser` 新增 `RAW_CONTENT_FORMAT` 类属性（默认 `"binary"`）
- [x] 2.2 实现 `DocumentParser._read_content(doc)` 基类方法（处理 raw_content / file:// 统一读取）
- [x] 2.3 实现 `DocumentParser._cleanup_raw_content(doc)` 方法
- [x] 2.4 新增 `_BaseParseState` dataclass（doc_id, doc_version, elements, _seq, _section_path, _next_seq()）
- [x] 2.5 更新 `tests/test_parser_registry.py` 验证基类新方法

## 3. 注册表增强

- [x] 3.1 实现 `ParserRegistry.unregister(source_type)` 方法（幂等）
- [x] 3.2 `register()` 方法增加 `priority: int = 0` 参数
- [x] 3.3 低优先级注册时不覆盖高优先级，记录 WARNING
- [x] 3.4 实现 `ParserRegistry.get_all()` 返回 `dict[str, DocumentParser]`
- [x] 3.5 更新 `tests/test_parser_registry.py`（注销、优先级、get_all 测试）

## 4. 入口修正

- [x] 4.1 修正 `parsers/__init__.py`：导出全部 6 个解析器类
- [x] 4.2 `app/core/deps.py`：确认注册代码使用正确的 import 路径
- [x] 4.3 `ingestion/pipeline.py`：用 `parser.RAW_CONTENT_FORMAT` 替代硬编码 `{"markdown", "md", "txt", "text"}` 判断

## 5. 全量验证

- [ ] 5.1 运行 `pytest tests/test_parser_utils.py tests/test_parser_registry.py -v`
- [ ] 5.2 运行 `pytest tests/ -v` 确认无回归
