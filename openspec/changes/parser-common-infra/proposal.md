## Why

6 个文档解析器之间存在严重代码重复：`VIDEO_URL_RE` 在 6 个文件中逐字拷贝、`_read_content()` 逻辑 6 份完全相同、`_guess_mime()` 的 MIME 表在 5 个文件中互不一致、`_AssetRecord` 和 `_*ParseState` 在 3-5 个文件中各自定义。此外，`ParserRegistry` 缺少注销能力，`IngestionPipeline` 硬编码了解析器的内容类型偏好。本次变更建立公共基础设施层，从源头消除重复。

## What Changes

- **新建 `parsers/utils.py`**：统一 MIME 映射表、视频/HTTP URL 正则、文本规范化函数、`AssetRecord` dataclass
- **增强 `DocumentParser` 基类**：新增 `RAW_CONTENT_FORMAT` 类属性、`_read_content(doc)` 基类方法、`_cleanup_raw_content(doc)`、`_BaseParseState` dataclass
- **增强 `ParserRegistry`**：`unregister()` 注销方法、`register()` 支持 `priority` 参数、`get_all()` 诊断方法
- **修正 `parsers/__init__.py`**：完整导出全部 6 个解析器
- **Pipeline 解耦**：`IngestionPipeline` 通过 `parser.RAW_CONTENT_FORMAT` 决定字节解码，不再硬编码类型列表

## Capabilities

### New Capabilities
- `parser-common-utilities`: 解析器公共工具模块，包含统一的 MIME 映射、URL 正则、文本规范化、AssetRecord、内容读取与清理、_BaseParseState 基类

### Modified Capabilities
- `parser-registry`: 注册表支持解析器注销、优先级覆盖和全量查询

## Impact

- **新增文件**：`parsers/utils.py`
- **修改文件**：`parsers/base.py`、`parsers/registry.py`、`parsers/__init__.py`、`ingestion/pipeline.py`、`app/core/deps.py`
- **测试**：新增 `tests/test_parser_utils.py`，更新 `tests/test_parser_registry.py`
- **API 兼容**：无 **BREAKING** 变更，所有已有解析器接口不变
- **依赖**：无新增外部依赖
