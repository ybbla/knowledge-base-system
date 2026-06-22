## Why

6 个文档解析器（PDF/Markdown/DOCX/HTML/PPTX/XLSX）存在严重代码重复（`VIDEO_URL_RE`、`_read_content`、`_guess_mime`、`_AssetRecord`、`_*ParseState` 分别在 3-6 个文件中逐字拷贝），加之多个逻辑缺陷（HtmlParser 序列化重解析性能陷阱、XLSX 双加载内存翻倍、PptxParser 列表判定过激等），导致维护成本高、行为不一致、修复一处需同步多文件。本次变更系统性地消除重复、修复已知缺陷、统一解析器行为。

## What Changes

- **提取公共基类方法**：将 `_read_content`、`_guess_mime`、`_normalize_text`、`_AssetRecord`、`_ParseState` 等跨解析器重复代码提升到 `DocumentParser` 基类或新建的 `parsers/utils.py`
- **统一正则与常量**：`VIDEO_URL_RE`、`HTTP_URL_RE`、`ATTACHMENT_EXTENSIONS` 等全局常量抽取到公共模块，消除 6 处重复定义
- **统一 MIME 映射表**：合并 5 个解析器各自维护的 MIME 表为一处，消除不一致（如 `.bmp` 在 HTML 解析器中缺失、`.tiff` 仅在 PDF 中定义）
- **修复 HtmlParser 性能陷阱**：`_text_without_nested_blocks()` 不再序列化重解析，改为直接遍历 DOM 树
- **修复 XLSX 双加载**：改为单次 `load_workbook` + 按需读取公式，减少内存占用
- **修复 PptxParser 列表误判**：BODY 占位符不再强制判为列表，增加更精确的列表检测条件
- **修复 MarkdownParser**：blockquote 语义保留、链接 URL 作为 Asset 提取
- **修复 DocxParser**：支持非英文样式名（"标题 1"、"Titre 1" 等）
- **修复 PdfParser**：扫描件降级处理（标记 `needs_ocr` 而非抛异常）、`raw_content` 解析后清理
- **修复 `__init__.py`**：完整导出全部解析器
- **Pipeline 解耦**：移除 `IngestionPipeline` 中对 source_type 的硬编码类型判断，由解析器自行声明内容类型偏好
- **HtmlParser 递归保护**：添加最大深度参数防止深层嵌套 HTML 栈溢出

## Capabilities

### New Capabilities
- `parser-common-utilities`: 解析器公共工具模块，包含统一的 MIME 映射、URL 正则、内容读取、文本规范化、Asset 创建与去重、ParseState 基类

### Modified Capabilities
- `parser-registry`: 注册表支持解析器优先级和运行时替换
- `pdf-parsing`: 共享公共工具模块，扫描件降级处理，raw_content 清理
- `docx-parsing`: 共享公共工具模块，非英文样式名支持
- `html-parsing`: 共享公共工具模块，`_text_without_nested_blocks` 性能修复，递归深度保护
- `pptx-parsing`: 共享公共工具模块，列表判定逻辑修正，`_normalize_text` 行为统一
- `xlsx-parsing`: 共享公共工具模块，单次加载优化
- `markdown-parsing`: （新建 spec）共享公共工具模块，blockquote 语义保留，链接 URL 提取

## Impact

- **代码量**：预计净减少 400-600 行重复代码
- **受影响文件**：`parsers/base.py`、`parsers/registry.py`、`parsers/__init__.py`、全部 6 个解析器文件、`ingestion/pipeline.py`、`app/core/deps.py`、新增 `parsers/utils.py`
- **测试文件**：需更新 `test_parser_registry.py`、各解析器测试文件
- **API 兼容性**：解析器输出 `ParseResult` 结构不变，对外 API 无 **BREAKING** 变更
- **数据库**：无 schema 变更
- **依赖**：无新增外部依赖
