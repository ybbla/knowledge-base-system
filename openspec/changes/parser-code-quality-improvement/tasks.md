## 1. 公共工具模块 (`parsers/utils.py`)

- [ ] 1.1 创建 `parsers/utils.py`，包含统一的 MIME 映射表 `MIME_MAP` 和 `guess_mime(url, asset_type)` 函数
- [ ] 1.2 定义 `VIDEO_URL_RE`、`HTTP_URL_RE` 正则和 `ATTACHMENT_EXTENSIONS` 常量
- [ ] 1.3 实现 `normalize_text(text)` 函数，统一空白归一化 + HTML 实体解码
- [ ] 1.4 定义 `AssetRecord` dataclass 和 `asset_deduplicate_key()` 工具函数
- [ ] 1.5 编写 `tests/test_parser_utils.py` 单元测试（覆盖 MIME 推断、正则匹配、文本规范化、去重键）

## 2. 基类增强 (`parsers/base.py`)

- [ ] 2.1 新增 `RAW_CONTENT_FORMAT` 类属性（默认 `"binary"`）到 `DocumentParser`
- [ ] 2.2 实现 `DocumentParser._read_content(doc)` 基类方法，根据 `RAW_CONTENT_FORMAT` 返回 `bytes` 或 `str`
- [ ] 2.3 实现 `DocumentParser._cleanup_raw_content(doc)` 便捷方法
- [ ] 2.4 新增 `_BaseParseState` dataclass，含 `doc_id`、`doc_version`、`elements`、`_seq`、`_section_path` 和 `_next_seq()` 方法
- [ ] 2.5 更新 `tests/test_parser_registry.py` 验证基类新增属性和方法

## 3. 注册表增强 (`parsers/registry.py`)

- [ ] 3.1 实现 `ParserRegistry.unregister(source_type)` 方法（幂等，不报错）
- [ ] 3.2 `register()` 方法增加 `priority: int = 0` 参数，高优先级覆盖低优先级
- [ ] 3.3 实现 `ParserRegistry.get_all()` 方法返回所有已注册的 `{source_type: parser}` 映射
- [ ] 3.4 更新 `tests/test_parser_registry.py` 补充注销、优先级、get_all 测试用例

## 4. MarkdownParser 迁移

- [ ] 4.1 声明 `RAW_CONTENT_FORMAT = "text"`，删除 `_read_content()` 方法，改用基类实现
- [ ] 4.2 删除 `VIDEO_URL_RE` 和 `_guess_mime()`，改用 `utils` 模块导入
- [ ] 4.3 `_ParseState` 继承 `_BaseParseState`，移除重复字段
- [ ] 4.4 blockquote 处理：`blockquote_open`/`blockquote_close` 设置状态标记，段落添加 `metadata.blockquote=true`
- [ ] 4.5 链接 URL 提取：在 `_process_token` 的 `link` 类型中创建 attachment Asset
- [ ] 4.6 `parse()` 末尾调用 `_cleanup_raw_content(doc)`
- [ ] 4.7 更新 `tests/test_ingestion_markdown.py`（如存在）或运行现有测试确认回归通过

## 5. HtmlParser 迁移

- [ ] 5.1 声明 `RAW_CONTENT_FORMAT = "text"`，删除 `_read_content()`、`_decode()`，改用基类实现
- [ ] 5.2 删除 `VIDEO_URL_RE`、`HTTP_URL_RE`、`ATTACHMENT_EXTENSIONS` 和 `_guess_mime()`，改用 `utils` 模块导入
- [ ] 5.3 删除 `_AssetRecord` 本地定义，改用 `utils.AssetRecord`
- [ ] 5.4 替换 `_normalize_text()` 为 `utils.normalize_text()`
- [ ] 5.5 `_HtmlParseState` 继承 `_BaseParseState`
- [ ] 5.6 重写 `_text_without_nested_blocks()`：直接遍历 DOM 子元素收集文本，跳过嵌套 `BLOCK_TAGS`
- [ ] 5.7 `_walk_children()` 增加 `depth` 参数，默认上限 256，超出时安全截断
- [ ] 5.8 `parse()` 末尾调用 `_cleanup_raw_content(doc)`
- [ ] 5.9 更新 `tests/test_ingestion_html.py` 补充性能修复和深度保护的测试

## 6. PdfParser 迁移

- [ ] 6.1 删除 `_read_content()` 方法，改用基类实现
- [ ] 6.2 删除 `VIDEO_URL_RE`、`HTTP_URL_RE`、`ATTACHMENT_EXTENSIONS` 和 `_guess_mime()`/`_guess_image_mime()`，改用 `utils` 模块导入
- [ ] 6.3 删除 `_AssetRecord` 本地定义，改用 `utils.AssetRecord`
- [ ] 6.4 `_PdfParseState` 继承 `_BaseParseState`
- [ ] 6.5 扫描件降级处理：无文本有图片时，不抛异常，设置 `doc.metadata["needs_ocr"]=true`，保留图片 Asset，生成 `unknown` 占位元素
- [ ] 6.6 `parse()` 末尾调用 `_cleanup_raw_content(doc)`
- [ ] 6.7 更新 `tests/test_ingestion_pdf.py` 补充扫描件降级测试

## 7. DocxParser 迁移

- [ ] 7.1 删除 `_read_content()` 方法，改用基类实现
- [ ] 7.2 删除 `VIDEO_URL_RE` 和本地 MIME 处理，改用 `utils` 模块导入
- [ ] 7.3 `_DocxParseState` 继承 `_BaseParseState`
- [ ] 7.4 `_process_paragraph()` 增强样式名识别：增加中文"标题"、法文"Titre"、德文"Überschrift"等关键词匹配，并通过 `WD_STYLE_TYPE.PARAGRAPH` 二次验证
- [ ] 7.5 `parse()` 末尾调用 `_cleanup_raw_content(doc)`
- [ ] 7.6 更新 `tests/test_ingestion_docx.py`（如存在）或运行现有测试确认回归通过

## 8. PptxParser 迁移

- [ ] 8.1 删除 `_read_content()` 方法，改用基类实现
- [ ] 8.2 删除 `VIDEO_URL_RE`、`AUDIO_URL_RE`、`HTTP_URL_RE` 和 `_guess_mime()`，改用 `utils` 模块导入
- [ ] 8.3 删除 `_AssetRecord` 本地定义，改用 `utils.AssetRecord`
- [ ] 8.4 替换 `_normalize_text()` 为 `utils.normalize_text()`
- [ ] 8.5 `_PptxParseState` 继承 `_BaseParseState`
- [ ] 8.6 修正 `_is_list_shape()`：BODY 占位符不再强制判为列表，仅当有缩进层级差异（`level > 0`）或明确列表结构时才返回 True
- [ ] 8.7 `parse()` 末尾调用 `_cleanup_raw_content(doc)`
- [ ] 8.8 更新 `tests/test_ingestion_pptx.py` 补充列表判定修正测试

## 9. XlsxParser 迁移

- [ ] 9.1 删除 `_read_content()` 方法，改用基类实现
- [ ] 9.2 删除 `VIDEO_URL_RE`、`HTTP_URL_RE` 和 `_guess_mime()`，改用 `utils` 模块导入
- [ ] 9.3 `_XlsxParseState` 继承 `_BaseParseState`
- [ ] 9.4 改为单次加载：仅 `load_workbook(raw, data_only=True, read_only=True)`，删除 `formula_wb` 二次加载
- [ ] 9.5 实现 `_extract_formula_from_zip()` 方法：从 zip 原始 XML 中按需提取公式文本（仅对缓存值缺失的单元格触发）
- [ ] 9.6 优化 `_find_regions()`：构建 `set[(row,col)]` 用于 O(1) 查空区域，避免笛卡尔积产生的空区域遍历
- [ ] 9.7 `parse()` 末尾调用 `_cleanup_raw_content(doc)`
- [ ] 9.8 更新 `tests/test_ingestion_xlsx.py` 补充单次加载、公式回退和稀疏区域优化测试

## 10. Pipeline 与入口解耦

- [ ] 10.1 修改 `ingestion/pipeline.py`：删除 `{"markdown", "md", "txt", "text"}` 硬编码类型判断，改为读取 `parser.RAW_CONTENT_FORMAT` 决定 decode 行为
- [ ] 10.2 更新 `app/core/deps.py`：`ParserRegistry` 注册时使用完整的 `parsers` 包导入（`from parsers import *`），修正 `__init__.py` 导出
- [ ] 10.3 修正 `parsers/__init__.py`：完整导出全部 6 个解析器类

## 11. 全量测试与回归验证

- [ ] 11.1 运行全部 parser 单元测试：`pytest tests/test_parser_registry.py tests/test_parser_utils.py -v`
- [ ] 11.2 运行全部 ingestion 测试：`pytest tests/test_ingestion_*.py -v`
- [ ] 11.3 运行集成测试：`pytest tests/integration/ -v`
- [ ] 11.4 运行全量测试：`pytest tests/ -v`，确认无回归
- [ ] 11.5 启动后端服务，通过 Playwright 验证前端文档上传解析功能正常
