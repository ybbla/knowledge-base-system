## Context

6 个解析器目前各自维护重复的正则、MIME 表、内容读取、文本规范化和内部状态管理代码。`DocumentParser` 基类仅定义了 `supports()` 和 `parse()` 两个抽象方法，未提供任何公共逻辑。`ParserRegistry` 只支持注册和查询，缺少运行时管理能力。

约束：现有解析器接口不可变，下游管线不感知内部重构。

## Goals / Non-Goals

**Goals:**
- 建立 `parsers/utils.py` 公共模块，消除正则、MIME 等重复定义
- 在 `DocumentParser` 基类提供 `_read_content`、`_cleanup_raw_content` 和 `_BaseParseState`
- `ParserRegistry` 支持注销、优先级和全量查询
- Pipeline 通过 `RAW_CONTENT_FORMAT` 解耦

**Non-Goals:**
- 不改动各解析器的 `parse()` 核心逻辑（后续 change 逐个迁移）
- 不引入新依赖

## Decisions

### 1. 公共代码分两层：`utils.py` + 基类方法

- **`parsers/utils.py`**：纯函数和常量（MIME_MAP、正则、`normalize_text`、`AssetRecord`）
- **`DocumentParser` 基类**：实例相关方法（`_read_content`、`_cleanup_raw_content`、`_BaseParseState`）

### 2. `_read_content` 通过 `RAW_CONTENT_FORMAT` 决定返回类型

```python
class DocumentParser(ABC):
    RAW_CONTENT_FORMAT: Literal["text", "binary"] = "binary"

    def _read_content(self, doc: Document) -> str | bytes:
        raw = doc.metadata.get("raw_content", ...)
        if doc.source_uri.startswith("file://"):
            filepath = resolve_file_uri(doc.source_uri)
            raw = filepath.read_bytes() if filepath.exists() else ...
        if self.RAW_CONTENT_FORMAT == "text" and isinstance(raw, bytes):
            return raw.decode("utf-8")
        return raw
```

`MarkdownParser` 和 `HtmlParser` 覆写为 `"text"`，其余保持 `"binary"`。

### 3. `_BaseParseState` 使用 dataclass 继承

```python
@dataclass
class _BaseParseState:
    doc_id: str
    doc_version: int
    elements: list[ParsedElement] = field(default_factory=list)
    _seq: int = 0
    _section_path: list[str] = field(default_factory=list)

    def _next_seq(self) -> int: ...
```

各解析器继承此基类并扩展特有字段。

### 4. Registry 优先级：高覆盖低，同优先级后覆盖前

### 5. Pipeline 解耦：推断 `RAW_CONTENT_FORMAT` 而非硬编码

```python
# 旧：if doc.source_type.lower() in {"markdown", "md", "txt", "text"}: decode
# 新：if parser.RAW_CONTENT_FORMAT == "text": decode
```

## Risks / Trade-offs

- **[风险] `_read_content` 行为变更**：各解析器当前实现略有差异（bytes vs str 处理），统一到基类可能引入边界差异。→ **缓解**：基类方法综合了所有现有路径，全量测试覆盖
- **[风险] dataclass 继承在 Python 3.10 有已知 edge case**：→ **缓解**：所有字段显式使用 `field()`，已验证

## Migration Plan

1. 新建 `parsers/utils.py`（不影响现有代码）
2. 修改 `DocumentParser` 基类（新增方法不影响现有子类）
3. 修改 `ParserRegistry`（新增方法，保持向后兼容）
4. 修改 Pipeline（行为等价，纯重构）
5. 本 change 不迁移解析器，后续 change 逐个改造

**回滚**：`git revert` 单 commit
