# Parser Common Utilities

## Purpose

提供所有文档解析器共享的公共工具模块（`parsers/utils.py`），消除跨解析器的代码重复，统一 MIME 推断、URL 正则、内容读取、文本规范化和 Asset 创建去重行为。

## Requirements

### Requirement: 提供统一的 MIME 类型推断

系统 SHALL 在公共工具模块中维护唯一的 MIME 映射表，覆盖所有解析器需要的文件扩展名 → MIME 类型映射，并提供 `guess_mime(url, asset_type)` 函数。

#### Scenario: 推断常见图片 MIME 类型

- **WHEN** 调用 `guess_mime("image.png", AssetType.image)`
- **THEN** 返回 `"image/png"`
- **AND** 对 `.jpg`、`.jpeg`、`.gif`、`.webp`、`.bmp`、`.svg` 同样返回对应 MIME

#### Scenario: 推断视频 MIME 类型

- **WHEN** 调用 `guess_mime("demo.mp4", AssetType.video)`
- **THEN** 返回 `"video/mp4"`
- **AND** 对 `.webm`、`.mov`、`.m4v` 同样返回对应 MIME

#### Scenario: 未识别的扩展名回退到类型通配

- **WHEN** 调用 `guess_mime("file.xyz", AssetType.image)`
- **THEN** 返回 `"image/*"`
- **AND** 对 `AssetType.video` 返回 `"video/*"`
- **AND** 对其他类型返回 `"application/octet-stream"`

### Requirement: 提供统一的 URL 识别正则

系统 SHALL 在公共工具模块中定义 `VIDEO_URL_RE`、`HTTP_URL_RE` 正则模式及 `ATTACHMENT_EXTENSIONS` 常量，供所有解析器共用。

#### Scenario: 识别视频 URL

- **WHEN** 用 `VIDEO_URL_RE` 匹配 `https://example.com/demo.mp4`
- **THEN** 匹配成功
- **AND** 对 YouTube、Vimeo、`.webm`、`.mov`、`.m4v` URL 同样匹配成功

#### Scenario: 识别 HTTP URL

- **WHEN** 用 `HTTP_URL_RE` 匹配文本中的 `https://example.com/page`
- **THEN** 匹配成功
- **AND** 对 `http://` 前缀的 URL 同样匹配成功

### Requirement: 提供统一的文本规范化

系统 SHALL 在公共工具模块中提供 `normalize_text(text)` 函数，将连续空白字符（含换行、制表、回车）归一化为单个空格并去除首尾空白。

#### Scenario: 压缩连续空白

- **WHEN** 调用 `normalize_text("hello   world\n\t extra ")`
- **THEN** 返回 `"hello world extra"`

#### Scenario: HTML 实体解码

- **WHEN** 调用 `normalize_text("a&amp;b &lt; c")`
- **THEN** 返回 `"a&b < c"`

### Requirement: 提供统一的 Asset 记录和去重

系统 SHALL 在公共工具模块中定义 `AssetRecord` dataclass 和 `asset_deduplicate_key(asset_type, identifier)` 函数，供解析器统一去重逻辑。

#### Scenario: 按 content_hash 去重图片

- **WHEN** 同一文档中两处出现相同 sha256 的内嵌图片
- **THEN** 解析器 SHALL 仅创建一个 image Asset
- **AND** 两个 ParsedElement 通过 `asset_ids` 引用同一 Asset

#### Scenario: 按 URL + 类型去重外部资源

- **WHEN** 同一文档中两处引用相同视频 URL
- **THEN** 解析器 SHALL 仅创建一个 video Asset
- **AND** 后续引用复用已有 Asset

### Requirement: 提供 ParseState 基类

系统 SHALL 在 `parsers/base.py` 中提供 `_BaseParseState` dataclass，包含 `doc_id`、`doc_version`、`elements`、`_seq`、`_section_path` 共享字段和 `_next_seq()` 方法，各解析器的内部状态类继承此基类。

#### Scenario: 子类继承共享字段

- **WHEN** 创建 `_PdfParseState(doc_id="d1", doc_version=1)` 继承自 `_BaseParseState`
- **THEN** 实例自动拥有 `doc_id`、`doc_version`、`elements`、`_seq`、`_section_path` 字段
- **AND** 调用 `_next_seq()` 返回递增序号

#### Scenario: 子类扩展特有字段

- **WHEN** `_MarkdownParseState` 继承 `_BaseParseState` 并添加 `heading_level`、`in_table` 等字段
- **THEN** 子类可同时使用基类字段和自有字段
- **AND** 不影响其他解析器的 ParseState 子类

### Requirement: 统一内容读取方法

系统 SHALL 在 `DocumentParser` 基类中提供 `_read_content(doc)` 方法，处理从 `metadata.raw_content` 或 `file://` URI 读取内容的逻辑，子类通过 `RAW_CONTENT_FORMAT` 类属性声明期望的返回类型（`"text"` 或 `"binary"`）。

#### Scenario: 二进制格式读取字节

- **GIVEN** 解析器声明 `RAW_CONTENT_FORMAT = "binary"`
- **WHEN** `doc.metadata.raw_content` 为字节或 `doc.source_uri` 为 `file:///path/to/file.pdf`
- **THEN** `_read_content(doc)` 返回 `bytes`

#### Scenario: 文本格式读取字符串

- **GIVEN** 解析器声明 `RAW_CONTENT_FORMAT = "text"`
- **WHEN** `doc.metadata.raw_content` 为字符串或 `doc.source_uri` 指向文本文件
- **THEN** `_read_content(doc)` 返回 `str`

#### Scenario: 解析后清理 raw_content

- **WHEN** 解析器完成 `parse()` 后调用 `_cleanup_raw_content(doc)`
- **THEN** `doc.metadata` 中不再包含 `"raw_content"` 键
