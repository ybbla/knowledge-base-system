## Context

当前 Parser 接口：`parse(self, doc: Document) -> ParseResult`。内容通过 `doc.metadata["raw_content"]` 隐式传入。Pipeline 在上传后从 MinIO 读回内容注入 metadata，Parser 内部再通过 `_read_content()` 取出。

前置依赖：`remove-legacy-apis` 已删除旧版 `/ingest`、`/upload` 等端点。

调用场景分析（旧接口移除后）：

| 调用点 | 场景 | 内容来源 |
|--------|------|---------|
| `documents.py:445` | POST /documents/upload | ✅ 上传内存，直接传 |
| `documents.py:275` | POST /documents 创建后入库 | ❌ PG 已有文档，MinIO 降级 |
| `documents.py:659/663` | 恢复删除文档 | ❌ PG 已有文档，MinIO 降级 |
| `documents.py:707` | 重新入库 | ❌ PG 已有文档，MinIO 降级 |
| 测试 | 集成测试 | ❌ MinIO 降级 |

降级路径必须保留——5 个调用场景依赖它。

## Goals / Non-Goals

**Goals:**
- Parser 接口改为 `parse(doc, content)`，内容显式传入
- 上传路径：Pipeline 直接从上传拿内容，不走 MinIO 读回
- 降级路径：保留 MinIO 读取，通过 `CONTENT_IS_TEXT` 判断 str/bytes
- 删除 `_read_content()`、`_cleanup_raw_content()`、`RAW_CONTENT_FORMAT`
- 所有 6 个解析器适配新签名

**Non-Goals:**
- 不改动解析器的核心解析逻辑
- 不改动 `RecursiveLoader`（子文档仍通过 MinIO 读取）
- 不消除降级路径的 MinIO 读取（那是非上传场景的正常行为）

## Decisions

### 1. 接口签名

```python
def parse(self, doc: Document, content: bytes | str) -> ParseResult:
```

`content` 为必传参数，无默认值。Pipeline 保证调用时 content 已就绪。

### 2. 基类保留 `CONTENT_IS_TEXT`

```python
class DocumentParser(ABC):
    CONTENT_IS_TEXT: bool = False  # 仅降级路径使用
```

- `MarkdownParser.CONTENT_IS_TEXT = True`
- `HtmlParser.CONTENT_IS_TEXT = True`
- 其余保持 `False`

用途：降级路径从 MinIO 读到 bytes 后，根据此标记决定是否 `decode("utf-8")`。

### 3. upload_document() 改动

```python
# 当前：
source_hash, size = upload_api._hash_upload(file)
# ... MinIO 写入 ...
doc = ingestion_pipeline.ingest(doc)

# 改动后：
file.file.seek(0)
file_content = file.file.read()
source_hash = compute_hash(file_content)
size = len(file_content)
# ... MinIO 写入 ...
doc = ingestion_pipeline.ingest(doc, raw_content=file_content)
```

`_hash_upload()` 不再被 v1 上传接口调用（保留在 `upload_utils.py` 中供其他场景使用）。

### 4. Pipeline 降级路径

```python
def ingest(self, doc, raw_content=None, options=None):
    ...
    self._run_create(doc, raw_content, options or {})

def _run_create(self, doc, raw_content, options):
    parser = self._parser_registry.get(doc.source_type)

    if raw_content is None:
        if doc.source_uri.startswith("minio://"):
            raw_content = read_uri_bytes(doc.source_uri, self._minio_store)
        elif doc.source_uri.startswith("file://"):
            raw_content = Path(doc.source_uri[7:]).read_bytes()

        if parser.CONTENT_IS_TEXT and isinstance(raw_content, bytes):
            raw_content = raw_content.decode("utf-8")

    result = parser.parse(doc, raw_content)
```

### 5. 解析器改动（以 DocxParser 为例）

```python
# 当前
def parse(self, doc: Document) -> ParseResult:
    raw = self._read_content(doc)
    docx = DocxDocument(io.BytesIO(raw))
    ...
    self._cleanup_raw_content(doc)  # ① 新增的
    return ParseResult(...)

# 改动后
def parse(self, doc: Document, content: bytes | str) -> ParseResult:
    docx = DocxDocument(io.BytesIO(content))
    ...
    doc.source_hash = compute_hash(content)
    return ParseResult(...)
```

不再需要 `_read_content()`、`_cleanup_raw_content()`。

## Risks / Trade-offs

- **[风险] 大文件内存**：上传接口把整个文件读入内存。→ **缓解**：FastAPI `UploadFile` 默认对 <1MB 文件已在内存中；当前场景文件通常 < 50MB，可接受
- **[风险] 降级路径 `CONTENT_IS_TEXT` 与解析器实际期望不一致**：→ **缓解**：只有 MarkdownParser 和 HtmlParser 覆写为 `True`，与当前 `RAW_CONTENT_FORMAT` 逻辑完全一致；测试覆盖
- **[风险] `file://` 降级路径未充分测试**：→ **缓解**：保留现有 `file://` 测试，不新增也不删除
