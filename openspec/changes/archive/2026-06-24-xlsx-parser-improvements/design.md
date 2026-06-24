## Context

XlsxParser 当前有两个层面的问题：

**性能层面**（原有 design.md 覆盖）：
- 两次 `load_workbook`（`data_only=True` + `data_only=False`）内存翻倍
- `_find_regions()` 笛卡尔积产生大量空区域遍历
- 存在内联重复代码（本地 `VIDEO_URL_RE`、`HTTP_URL_RE`、`_guess_mime()`）

**功能层面**（本次补充）：
- 嵌入图片（Excel 中直接插入的图片）完全未被提取
- 链接 URL 类型分类粗糙：仅分 `video` vs `attachment`，图片链接（`.png`/`.jpg` 等）被错误归为 `attachment`
- 下游 `_prepare_assets()` 对 `AssetType.image` 调用 `process_image()`（含视觉理解），对 `AssetType.attachment` 只做简单存储。分类错误导致图片链接无法被正确理解和检索

依赖：`parser-common-infra` change 必须先完成（提供公共 `guess_mime`、`is_video_url`、`is_attachment_url` 等）。

## Goals / Non-Goals

**Goals:**
- 迁移到公共基础设施（使用 `parsers.utils` 模块）
- 单次加载 + 按需提取公式文本
- 稀疏区域检测优化
- **新增：提取工作表中嵌入的图片，创建 `AssetType.image` 的 Asset**
- **新增：链接 URL 细分为 image / video / attachment 三种类型**
- **新增：链接文字保留到 content 中（当前已满足，需在 spec 中明确约束）**

**Non-Goals:**
- 不新增图表（Chart）提取
- 不处理嵌入的 OLE 对象

## Decisions

### 1. 单次加载 + 公式预提取

```python
# 仅一次加载，data_only=True 读取缓存值
wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=False)
```

`data_only=True` 读取 Excel 保存的缓存计算值。公式文本通过 `_extract_all_formulas_from_zip(raw, sheet_index)` 从 zip 原始 XML **预提取**（每 sheet 一次 `finditer` 全量扫），返回 `{cell_ref: formula_text}` 映射。无论缓存值是否存在，所有公式单元格的 metadata 中都记录公式文本，与旧代码 `data_only=False` 的 `formula_wb` 行为一致。

> **注意**：`read_only=True` 模式下 `ws._images` 不可用（openpyxl 的只读模式不解析图片）。保持 `read_only=False` 以保证图片提取可用；单次加载优化通过删除 `formula_wb` 二次加载实现（仍为一次加载，`read_only=False`）。

```python
@staticmethod
def _extract_all_formulas_from_zip(raw: bytes, sheet_index: int) -> dict[str, str]:
    """从 zip 原始 XML 预提取当前工作表所有公式。"""
    formulas: dict[str, str] = {}
    sheet_xml_path = f"xl/worksheets/sheet{sheet_index}.xml"
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        sheet_xml = zf.read(sheet_xml_path).decode("utf-8")
    for match in re.finditer(
        r'<c\s+r="([A-Z]+[0-9]+)"[^>]*>\s*<f[^>]*>(.*?)</f>',
        sheet_xml, re.DOTALL,
    ):
        cell_ref = match.group(1)
        text = match.group(2).strip()
        formulas[cell_ref] = f"={text}" if not text.startswith("=") else text
    return formulas
```

在 `_collect_cells()` 中，始终从 `formulas_map` 查询公式（无论缓存值是否存在）：

```python
formula = formulas_map.get(source_cell.coordinate)
if formula:
    metadata["formula"] = formula
    metadata["formula_value_missing"] = not bool(value_text)
```

**与旧代码行为对比**：

| 场景 | 旧代码（formula_wb） | 新代码（预提取） |
|---|---|---|
| 缓存值存在 `=SUM(...)` → `3` | text=3, formula="=SUM(...)", formula_value_missing=false | text=3, formula="=SUM(...)", formula_value_missing=false ✅ |
| 缓存值缺失 `=SUM(...)` → None | text="=SUM(...)", formula="=SUM(...)", formula_value_missing=true | text="=SUM(...)", formula="=SUM(...)", formula_value_missing=true ✅ |
| 普通文本 "hello" | text="hello" | text="hello" ✅ |

### 2. 区域检测优化

预先构建 `occupied_rows: dict[int, set[int]]`（row → 该行所有有数据的列的集合），然后只对每个行分组和列分组的交集做检查。如果行分组内没有任何行的列落到列分组范围内，直接跳过。

```python
def _find_regions(cells):
    if not cells:
        return []
    occupied_rows: dict[int, set[int]] = {}
    for row, col in cells:
        occupied_rows.setdefault(row, set()).add(col)
    
    row_groups = _group_contiguous(sorted(occupied_rows.keys()))
    all_cols = sorted({col for _, col in cells})
    col_groups = _group_contiguous(all_cols)
    
    regions = []
    for row_start, row_end in row_groups:
        for col_start, col_end in col_groups:
            if not any(
                col_start in occupied_rows.get(r, set())
                or any(col_start <= c <= col_end for c in occupied_rows.get(r, set()))
                for r in range(row_start, row_end + 1)
            ):
                continue
            regions.append(_Region(row_start, row_end, col_start, col_end))
    return sorted(regions, key=lambda r: (r.min_row, r.min_col))
```

### 3. 嵌入图片提取（新增）

openpyxl 的 `ws._images` 列表包含工作表中所有嵌入图片。每张图片可通过 `img.anchor._from` 获取锚定单元格位置，通过 `img._data()` 获取二进制数据。

**关键设计：图片 Asset 必须关联到对应的单元格/ParsedElement**，确保溯源精确。

流程分两步：

**步骤 A**：`_collect_cells()` 之前调用 `_extract_sheet_images()`，返回 `dict[tuple[int, int], list[str]]`（单元格位置 → 图片 asset_id 列表）和创建好的 Asset 列表。

```python
def _extract_sheet_images(
    self, ws, doc, sheet_name, sheet_index, assets
) -> dict[tuple[int, int], list[str]]:
    """提取工作表中嵌入的图片，创建 Asset 并返回 单元格→asset_id 映射。
    
    Returns:
        {(row, col): [asset_id, ...]}  将图片关联到锚定单元格。
    """
    image_cell_map: dict[tuple[int, int], list[str]] = {}
    
    for idx, img in enumerate(ws._images):
        try:
            data = img._data()
        except Exception:
            continue
        
        # 获取锚定位置（0-based → 1-based）
        row, col = 0, 0
        try:
            anchor = img.anchor
            if hasattr(anchor, '_from'):
                row = anchor._from.row + 1
                col = anchor._from.col + 1
        except Exception:
            pass
        
        content_type = img.format or 'png'
        ext = content_type.lower()
        filename = f"image_{sheet_index}_{idx}.{ext}"
        
        asset = Asset(
            doc_id=doc.doc_id,
            asset_type=AssetType.image,
            original_uri=f"xlsx://{doc.doc_id}/media/{filename}",
            mime_type=guess_mime(f".{ext}", AssetType.image),
            status=AssetStatus.ready,
            metadata={
                "source": "xlsx_image",
                "sheet_name": sheet_name,
                "sheet_index": sheet_index,
                "cell": f"{get_column_letter(col)}{row}" if row and col else None,
                "row": row,
                "col": col,
            },
        )
        object.__setattr__(asset, '_data', data)
        assets.append(asset)
        
        if row and col:
            image_cell_map.setdefault((row, col), []).append(asset.asset_id)
    
    return image_cell_map
```

**步骤 B**：在 `_collect_cells()` 中，遍历 cells 时检查 `image_cell_map`，将对应位置的图片 asset_id 合并到该单元格的 asset_ids 中：

```python
# _collect_cells() 内部，创建 _CellInfo 之前：
cell_asset_ids = self._assets_from_cell(...)  # 原有链接资源

# 合并该位置的嵌入图片
image_asset_ids = image_cell_map.get((row, col), [])
if image_asset_ids:
    cell_asset_ids = image_asset_ids + cell_asset_ids  # 图片排前面
```

这样图片 Asset 通过 `_CellInfo.asset_ids` → `ParsedElement.asset_ids` → `Asset.source_element_id` 完整链路关联到对应的表格/段落元素。溯源时可以精确定位图片属于哪个单元格。

图片通过 `object.__setattr__(asset, '_data', data)` 存储原始二进制数据，与 `docx_parser.py` 的 `_build_image_asset_map()` 保持一致。下游 `process_image()` 通过 `asset._data` 读取。

### 4. 链接 URL 类型细分（新增）

当前 `_assets_from_cell()` 中只有 `video` vs `attachment` 二分。需要增加图片链接识别。

```python
@staticmethod
def _classify_link_asset_type(url: str) -> AssetType:
    """根据 URL 判断链接的资源类型。
    
    优先级：视频 > 图片 > 附件。
    复用 parsers.utils 的 is_video_url、is_attachment_url 和 MIME_MAP。
    """
    if is_video_url(url):
        return AssetType.video
    
    suffix = PurePosixPath(url.split('?', 1)[0]).suffix.lower()
    # 图片扩展名（与 docx_parser 的 _IMAGE_EXTENSIONS 保持一致）
    image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg', '.tiff', '.tif'}
    if suffix in image_exts:
        return AssetType.image
    
    if is_attachment_url(url):
        return AssetType.attachment
    
    # 无已知扩展名的 HTTP URL 默认归为 attachment
    return AssetType.attachment
```

修改 `_assets_from_cell()` 中 L247：
```python
# 旧代码
asset_type = AssetType.video if self._is_video_url(url) else AssetType.attachment

# 新代码
asset_type = self._classify_link_asset_type(url)
```

### 5. 超链接文字保留（现状确认）

当前实现已正确保留超链接文字：

```
cell.value = "说明书"        → value_text = "说明书"  → text = "说明书"
cell.hyperlink.target = "https://example.com/manual.pdf"
```

`text` 始终是单元格的显示文字（链接文字），URL 通过 `hyperlink` 参数单独传入 `_assets_from_cell()`。链接文字不会被 URL 覆盖（L163-164 仅在 text 为空时用 URL 填充，这是一种降级策略）。

无需修改。

### 6. 迁移方式

- 删除本地 `VIDEO_URL_RE`、`HTTP_URL_RE`、`_guess_mime()`、`_is_video_url()`，改用 `parsers.utils` 公共实现
- `_XlsxParseState` 继承 `_BaseParseState`，移除重复的 `doc_id`、`doc_version`、`elements`、`_seq`、`_next_seq()` 字段
- `parse()` 末尾调用 `self._cleanup_raw_content(doc)`
