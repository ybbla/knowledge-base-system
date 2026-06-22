# XLSX 解析器改进实施计划

## 目标

改进 `xlsx_parser.py`，使其能正确处理：
1. **图片**：单元格中的图片，提取并作为 `DocumentResource` 返回
2. **超链接**：真实超链接（文字覆盖 + ctrl+单击可访问），保留链接文字到 content，提取 URL 作为资源
3. **单元格合并**：正确处理合并单元格，合并区域内的内容正确映射
4. **多 Sheet**：正确处理多个工作表

链接类型包括：图片链接、视频链接、文档链接，均需作为资源被正确处理。

## 当前状态分析

### 当前 xlsx_parser.py 的问题

1. **不支持图片提取**：openpyxl 可以读取图片，但当前代码未处理
2. **不支持超链接提取**：单元格的 `.hyperlink` 属性未读取，超链接文字和 URL 都丢失了
3. **合并单元格处理不完整**：当前代码调用了 `_unmerge_cells()` 但只是简单填充，没有正确处理合并区域的语义
4. **多 Sheet 处理已基本正确**：当前遍历所有 sheet，但内容结构可以优化

### 相关代码参考

- `docx_parser.py`：展示了如何提取图片（从 `docx` XML 关系中提取），以及如何处理超链接
- `parsers/utils.py`：提供了 `_extract_images_from_archive()` 工具函数，从 ZIP 中提取图片
- `base.py`：定义了 `ParserOutput`（包含 `content: str` 和 `resources: list[DocumentResource]`）
- `DocumentResource`：有 `resource_id`、`resource_type`、`filename`、`data`（bytes）字段

### 超链接处理的关键点

openpyxl 中，超链接存储在 `cell.hyperlink` 属性中：
- `cell.hyperlink.target`：URL 地址
- `cell.hyperlink.display`：显示文本（可能为 None）
- `cell.value`：单元格的显示值（即链接文字）

需要区分三种情况：
1. `cell.value` 有文字 + `cell.hyperlink` 存在 → 真实超链接，保留文字 + 提取 URL 作为资源
2. `cell.value` 是 URL 字符串但没有 hyperlink 对象 → 自动检测的 URL，也作为链接处理
3. 普通文本 → 正常保留

## 实施步骤

### 步骤 1：增强超链接提取

修改 `_parse_sheet()` 方法，在遍历单元格时检测超链接：

- 读取 `cell.hyperlink` 属性
- 如果存在超链接：
  - 保留 `cell.value`（链接文字）到 content 中
  - 创建 `DocumentResource`，类型为 `"link"`，data 包含 JSON `{"url": target, "text": display_text}`
  - 根据 URL 后缀判断链接子类型（image/video/document/other）
- 链接文字保留在单元格内容中，用 `[链接文字](URL)` 的 markdown 格式或保持原样

### 步骤 2：增强图片提取

利用 openpyxl 的 `_images` 属性（每个 worksheet 有 `._images` 列表）：

- 遍历 `ws._images` 获取所有图片
- 通过 `img.anchor._from.row` 和 `img.anchor._from.col` 获取图片位置
- 读取图片二进制数据（`img._data()`）
- 创建 `DocumentResource`，类型为 `"image"`
- 在对应单元格的 content 中插入图片占位符 `[图片: filename]`

### 步骤 3：优化合并单元格处理

当前 `_unmerge_cells()` 的改进：

- 合并区域的值来自左上角单元格
- 填充到所有被合并的单元格时，使用相同的值
- 确保合并区域内的内容不丢失、不重复

### 步骤 4：优化多 Sheet 输出格式

- 每个 Sheet 生成独立的段落/section
- 使用 Sheet 名称作为标题
- 保持 content 和 resources 的正确对应关系

### 步骤 5：更新测试

- 创建包含图片、超链接、合并单元格、多 Sheet 的测试 xlsx 文件
- 编写测试验证：
  - 图片资源被正确提取
  - 超链接资源被正确提取，链接文字保留
  - 合并单元格内容正确
  - 多 Sheet 内容正确

## 关键设计决策

### 超链接的资源类型判断

```python
def _classify_link_type(url: str) -> str:
    """根据 URL 后缀判断链接类型"""
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'}
    video_exts = {'.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv', '.webm'}
    doc_exts = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.md', '.csv'}
    
    lower = url.lower().split('?')[0]  # 去掉 query string
    ext = os.path.splitext(lower)[1]
    
    if ext in image_exts:
        return "image_link"
    elif ext in video_exts:
        return "video_link"
    elif ext in doc_exts:
        return "document_link"
    else:
        return "link"
```

### 超链接在 content 中的表示

保留单元格文字，在文字后追加链接信息。对于超链接单元格，content 格式为：
```
链接文字 [→ URL]
```

这样既保留了可读性，也保留了链接信息。

### 图片位置映射

openpyxl 中图片位置通过 `Anchor` 对象表示：
- `OneCellAnchor`：锚定到单个单元格
- `TwoCellAnchor`：锚定到单元格范围

使用 `img.anchor._from.row` 和 `img.anchor._from.col` 获取起始位置。

## 涉及的文件

1. **`knowledge_base_system/parsers/xlsx_parser.py`** — 主要修改文件
2. **`knowledge_base_system/tests/test_xlsx_parser.py`** — 测试更新
3. **`knowledge_base_system/tests/data/`** — 新增测试 xlsx 文件（通过代码生成）
4. **`openspec/changes/xlsx-parser-improvements/`** — OpenSpec 文档更新

## 风险与注意事项

1. **openpyxl 图片 API 不稳定性**：`_images` 是私有属性，不同版本可能变化。需要做好异常处理
2. **图片数据读取**：`img._data()` 在某些版本可能不存在，需要 fallback
3. **合并单元格与超链接/图片的重叠**：合并单元格区域内的超链接和图片需要特殊处理
4. **性能**：大型 xlsx 文件可能包含大量图片，需要注意内存使用
