## Context

当前解析器体系包含 6 个格式解析器，均继承 `DocumentParser` 抽象基类。详细分析发现：

- **6 个解析器逐字重复** `VIDEO_URL_RE` 正则、`_read_content()` 逻辑
- **5 个解析器各自维护** MIME 映射表（`.bmp`、`.svg`、`.tiff` 覆盖不一致）
- **3 个解析器各自定义** `_AssetRecord` 内部类（key 类型互不一致）
- **5 个解析器各自实现** `_*ParseState`（均含 `doc_id`、`doc_version`、`elements`、`_seq`、`_section_path`）
- **2 个解析器各自实现** `_normalize_text()`（空白处理行为不一致）
- **HtmlParser** 的 `_text_without_nested_blocks()` 每次调用序列化+重解析 HTML
- **XlsxParser** 同时打开两个完整 Workbook 实例
- **PptxParser** 的列表判定对 BODY 占位符过于激进
- **Pipeline** 硬编码了解析器的内容类型偏好

约束条件：所有现有解析器 API（`supports()`、`parse() → ParseResult`）不可变，下游 `IngestionPipeline`、`RecursiveLoader`、`SemanticExtractor` 不感知内部重构。

## Goals / Non-Goals

**Goals:**
- 消除跨解析器的代码重复（正则、MIME、URL 提取、内容读取、文本规范化、Asset 创建去重、ParseState）
- 修复 6 个已知逻辑缺陷（HtmlParser 性能、XLSX 双加载、PptxParser 列表误判、MarkdownParser blockquote/链接丢失、DocxParser 非英文样式、PdfParser 扫描件处理）
- 统一各解析器的空白归一化、MIME 推断、Asset 去重行为
- Pipeline 与解析器间通过基类属性解耦，不再硬编码类型判断
- 所有现有测试通过，`ParseResult` 输出兼容

**Non-Goals:**
- 不新增解析器格式支持（不新增 `doc`、`epub` 等解析器）
- 不修改 `ElementType` 枚举（不新增 `blockquote` 等类型——待后续独立 change）
- 不引入 OCR 能力（扫描件仅标记 `needs_ocr`，不做 OCR 集成）
- 不修改 `KnowledgeChunk`、`SemanticExtractor`、索引写入等下游逻辑
- 不新增外部依赖

## Decisions

### 1. 公共代码放置策略：`parsers/utils.py` + `DocumentParser` 扩展

**决策**：新建 `parsers/utils.py` 存放纯函数/常量，同时在 `DocumentParser` 基类中提供实例方法封装。

**理由**：
- 纯函数（正则匹配、MIME 推断、空白归一化）天然适合独立模块，便于单元测试
- `_read_content` 和 `_create_asset` 需要访问 `doc` 上下文，适合做基类方法
- 避免把所有东西塞进 `DocumentParser` 导致基类臃肿

**备选方案**：全部放入 `DocumentParser` 基类 → 拒绝，因为正则/MIME 等纯数据应与实例解耦

### 2. ParseState 基类设计

**决策**：在 `parsers/base.py` 新增 `_BaseParseState` dataclass，包含共享字段和 `_next_seq()`、`flush_elements()`。

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

各解析器的 `_*ParseState` 继承此类，只添加自己特有的字段（如表格状态、列表状态等）。

### 3. MIME 表统一方案

**决策**：在 `parsers/utils.py` 维护单份权威 MIME 映射表，合并所有解析器现存的条目。

关键词映射：扩展名 → MIME 字符串。同时保留 `guess_mime(url, asset_type)` 函数作为回退。

**备选方案**：使用 `mimetypes` 标准库 → 拒绝，标准库不认识 `.webp`、`.m4v` 等现代格式

### 4. XLSX 单次加载方案

**决策**：改为仅加载 `data_only=True`，公式文本通过轻量 Zip 读取获取。

```
load_workbook(raw, data_only=True, read_only=True)  # 主加载，轻量
# 公式文本：仅在需要时从 zip 归档读取 sharedStrings 和 sheet XML
```

`data_only=True` 读取 Excel 保存时写入的缓存计算值，覆盖率足够高。公式文本降级为可选 metadata（仅当缓存值缺失时尝试读取公式原文）。

**备选方案**：保持双加载但用 `read_only=True` → 仍翻倍内存，不采纳

### 5. HtmlParser `_text_without_nested_blocks` 优化

**决策**：不再做 `str(tag)` → `BeautifulSoup(..., "html.parser")` 的序列化回环。改为直接遍历子元素：收集 `NavigableString` 文本，遇到 `BLOCK_TAGS` 中的子标签则跳过（不递归进入该子树）。

```python
def _text_without_nested_blocks(self, tag: Tag) -> str:
    parts = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag) and child.name not in self.BLOCK_TAGS:
            parts.append(child.get_text(" ", strip=True))
    return self._normalize_text(" ".join(parts))
```

### 6. Pipeline 解耦方式

**决策**：在 `DocumentParser` 基类增加类属性 `RAW_CONTENT_FORMAT: Literal["text", "binary"] = "binary"`。

- `MarkdownParser` 覆写为 `"text"`
- `HtmlParser` 覆写为 `"text"`
- 其余保持默认 `"binary"`

Pipeline 不再硬编码 `{"markdown", "md", "txt", "text"}`，改为读取 `parser.RAW_CONTENT_FORMAT`。

### 7. ParserRegistry 增强

**决策**：
- 新增 `unregister(source_type)` 方法
- `register()` 增加 `priority: int = 0` 参数（高优先级覆盖低优先级）
- 新增 `get_all() → dict[str, DocumentParser]` 方法供诊断使用

### 8. `raw_content` 清理

**决策**：在 `parse()` 方法返回前统一清理 `doc.metadata.pop("raw_content", None)`，由各解析器在 `parse()` 末尾调用。基类不强制（保持子类灵活性），但提供 `_cleanup_raw_content(doc)` 便捷方法。

## Risks / Trade-offs

- **[风险] XLSX 公式文本降级**：改用 `data_only=True` 单次加载后，某些从未被 Excel 保存过的文件可能缺失缓存值，公式文本也无法获取。→ **缓解**：提供 `_extract_formula_text_from_zip()` 轻量回退方法，从 zip 原始 XML 中读取公式，仅对缓存值缺失的单元格触发
- **[风险] HtmlParser 文本提取行为变化**：优化 `_text_without_nested_blocks` 后，文本输出可能因空白处理差异与旧版微调。→ **缓解**：保持归一化管道一致（`_normalize_text` → `re.sub(r"\s+", " ", ...)`），编写回归测试
- **[风险] ParseState 继承链**：引入 `_BaseParseState` 后，dataclass 继承在某些 Python 版本有坑（字段顺序、默认值）。→ **缓解**：所有字段使用 `field(default_factory=...)` 或 `field(default=...)` 显式设置，已验证 Python 3.10+ 支持

## Migration Plan

1. 先建 `parsers/utils.py`，迁移纯函数（MIME、正则、文本工具）
2. 扩展 `DocumentParser` 基类（`_read_content`、`_cleanup_raw_content`、`RAW_CONTENT_FORMAT`、`_BaseParseState`）
3. 逐个改造解析器，每个改完后跑对应测试
4. 最后改造 Pipeline 和 deps
5. 全量测试验证

**回滚方案**：所有变更在同一个 git commit 中，`git revert` 即可完整回退。公共模块不影响现有接口——如果出现问题，各解析器可暂时回退到内联实现。

## Open Questions

- MarkdownParser 的 `blockquote` 目前无对应 `ElementType`，暂时保留文本内容但标记 `metadata={"blockquote": True}`，待后续新增 ElementType 后再迁移——接受吗？
- `_BaseParseState` 是否需要线程安全（seq 用锁）？当前所有解析器单线程使用，暂不加锁
