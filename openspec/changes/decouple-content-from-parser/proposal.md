## Why

当前 Parser 通过 `doc.metadata["raw_content"]` 隐式接收内容——Pipeline 把从 MinIO 读回的原始字节塞进 metadata，Parser 再从中取出。这导致三个问题：

1. **职责不清**：内容获取（MinIO 读 / 上传内存）是 Pipeline 的职责，却通过 metadata 作为隐式通道传递给 Parser
2. **MinIO 写后即读**：上传文件刚写入 MinIO，ingest 立即读回——纯粹浪费一次网络 IO（上传路径）
3. **事后清理**：`_cleanup_raw_content()`、`_read_content()`、`RAW_CONTENT_FORMAT` 这些基类方法的存在，恰恰说明接口设计有问题——如果内容显式传入，它们全都不需要

本次变更将 `parse(doc)` 改为 `parse(doc, content)`，内容由 Pipeline 显式传入，Parser 只做格式转换。降级路径（非上传场景，如后台重处理）保留 MinIO 读取能力。

## What Changes

- **Parser 接口**：`parse(self, doc: Document, content: bytes | str) -> ParseResult` — content 为必传参数
- **基类保留 `CONTENT_IS_TEXT: bool = False`**：仅用于降级路径判断 str/bytes，MarkdownParser/HtmlParser 覆写为 `True`
- **Pipeline**：上传路径直接传 `raw_content`；降级路径从 MinIO 读回后根据 `CONTENT_IS_TEXT` 决定 decode
- **upload_document()**：`file.file.read()` 读入内存，MinIO 写入后 `raw_content` 直接传给 `ingest()`
- **基类清理**：删除 `_read_content()`、`_normalize_raw()`、`_cleanup_raw_content()`、`RAW_CONTENT_FORMAT`
- **6 个解析器**：删除 `_read_content()` 调用，直接使用 `content` 参数

## Capabilities

### Modified Capabilities
- `document-ingestion`: Pipeline 直接传递内容给 Parser，上传路径消除 MinIO 写后即读回环；`parse()` 签名变更为显式接收 content；`_read_content` / `_cleanup_raw_content` / `RAW_CONTENT_FORMAT` 从基类移除

## Impact

- **修改文件**：`parsers/base.py`、`ingestion/pipeline.py`、`app/api/v1/documents.py`、全部 6 个解析器文件
- **删除代码**：基类 `_read_content()`、`_normalize_raw()`、`_cleanup_raw_content()`、`RAW_CONTENT_FORMAT`
- **保留代码**：基类 `CONTENT_IS_TEXT: bool = False`（最小化，仅降级路径用）
- **API 兼容**：对外 API（`POST /api/v1/documents/upload`）不变，**BREAKING**：`DocumentParser.parse()` 签名变更
- **性能**：上传路径消除每次入库的 MinIO 读回网络 IO
- **测试**：更新全部解析器测试、Pipeline 测试
