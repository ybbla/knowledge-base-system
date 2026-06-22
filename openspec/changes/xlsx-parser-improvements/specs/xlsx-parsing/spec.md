## ADDED Requirements

### Requirement: Single-pass workbook loading

XlsxParser SHALL 使用单次 `load_workbook(data_only=True, read_only=False)` 加载工作簿，不再并行打开 `formula_wb`。`read_only=False` 保留以支持 `ws._images` 图片提取。

#### Scenario: 公式单元格缓存值存在

- **WHEN** 单元格 `A1` 包含公式 `=SUM(B1:B10)` 且 Excel 已缓存计算结果 `55`
- **THEN** `data_only=True` 返回 `55` 作为单元格文本
- **AND** `metadata.formula` 记录公式文本 `=SUM(B1:B10)`（从 zip XML 预提取）
- **AND** `metadata.formula_value_missing` 为 `false`

#### Scenario: 公式单元格缓存值缺失

- **WHEN** 单元格 `A1` 包含公式 `=SUM(B1:B10)` 且无缓存值（如第三方工具生成的 xlsx）
- **THEN** 从 zip 原始 XML 提取公式文本 `=SUM(B1:B10)`
- **AND** 单元格文本为公式文本
- **AND** `formula_value_missing` 元数据为 `true`

### Requirement: 从 zip 原始 XML 预提取公式文本

XlsxParser SHALL 提供 `_extract_all_formulas_from_zip(raw, sheet_index)` 方法，每 sheet 一次 `finditer` 全量解析 `xl/worksheets/sheet{sheet_index}.xml`，返回 `{cell_ref: formula_text}` 映射。无论缓存值是否存在，所有公式单元格的 metadata 中都记录公式文本。

#### Scenario: 预提取全部公式

- **WHEN** 工作表包含 `A1`（`=SUM(B1:B10)`）和 `C3`（`=VLOOKUP(...)`）两个公式
- **THEN** 方法返回 `{"A1": "=SUM(B1:B10)", "C3": "=VLOOKUP(...)"}`
- **AND** 仅打开 zip 一次（非逐单元格按需查询）

### Requirement: 嵌入图片提取

XlsxParser SHALL 遍历每个可见工作表的 `ws._images` 列表，提取所有嵌入图片并创建 `AssetType.image` 的 Asset。

#### Scenario: 工作表包含嵌入图片

- **WHEN** 工作表 "产品" 的 B2 单元格位置嵌入了一张 PNG 图片
- **THEN** 创建 `AssetType.image` 的 Asset
- **AND** Asset 的 `original_uri` 格式为 `xlsx://{doc_id}/media/image_{sheet_index}_{idx}.{ext}`
- **AND** Asset 的 metadata 包含 `sheet_name`、`sheet_index`、`cell`、`row`、`col`
- **AND** Asset 通过 `object.__setattr__(asset, '_data', data)` 存储原始二进制数据
- **AND** 图片的 asset_id 被合并到锚定单元格 (2, 2) 对应的 `_CellInfo.asset_ids` 中
- **AND** 最终图片 Asset 通过 `_CellInfo.asset_ids` → `ParsedElement.asset_ids` → `Asset.source_element_id` 完整链路关联到对应的表格或段落元素

#### Scenario: 工作表无嵌入图片

- **WHEN** 工作表不包含任何嵌入图片（`ws._images` 为空列表）
- **THEN** 不创建任何图片 Asset
- **AND** 不影响其他解析逻辑

#### Scenario: 图片数据读取失败

- **WHEN** `img._data()` 抛出异常
- **THEN** 静默跳过该图片
- **AND** 继续处理后续图片

### Requirement: 链接 URL 类型细分

XlsxParser SHALL 根据 URL 后缀将链接细分为 `video`、`image`、`attachment` 三种 AssetType，与 Markdown/DOCX 解析器保持一致。

#### Scenario: 视频链接

- **WHEN** 单元格包含超链接 `https://example.com/demo.mp4`
- **THEN** Asset 类型为 `video`

#### Scenario: 图片链接

- **WHEN** 单元格包含超链接 `https://example.com/photo.png`
- **THEN** Asset 类型为 `image`
- **WHEN** 单元格包含超链接 `https://example.com/logo.jpg`
- **THEN** Asset 类型为 `image`

#### Scenario: 文档链接

- **WHEN** 单元格包含超链接 `https://example.com/doc.pdf`
- **THEN** Asset 类型为 `attachment`
- **WHEN** 单元格包含超链接 `https://example.com/report.docx`
- **THEN** Asset 类型为 `attachment`

#### Scenario: 无已知扩展名的链接

- **WHEN** 单元格包含超链接 `https://example.com/page`（无文件扩展名）
- **THEN** Asset 类型默认为 `attachment`

### Requirement: 超链接文字保留

XlsxParser SHALL 保留超链接单元格的显示文字到 content 中，URL 单独作为资源提取。

#### Scenario: 超链接单元格有显示文字

- **WHEN** 单元格 B3 的 `value` 为 "说明书"，`hyperlink.target` 为 `https://example.com/manual.pdf`
- **THEN** 单元格文本为 "说明书"
- **AND** URL `https://example.com/manual.pdf` 作为 Asset 提取
- **AND** 单元格文本不被 URL 覆盖

#### Scenario: 超链接单元格无显示文字（降级策略）

- **WHEN** 单元格 B3 的 `value` 为 `None`，`hyperlink.target` 为 `https://example.com/manual.pdf`
- **THEN** 单元格文本为 `https://example.com/manual.pdf`（降级用 URL 填充）

## MODIFIED Requirements

### Requirement: Sparse region detection

XlsxParser SHALL 使用 `occupied_rows` 映射（`dict[int, set[int]]`）快速跳过空区域，而非对笛卡尔积每个候选区域做 O(n) 遍历。

#### Scenario: 稀疏工作表跳过空区域

- **WHEN** 工作表在 A1:B2 和 D5:E6 有数据，其余为空
- **THEN** 仅检测 A1:B2 和 D5:E6 两个区域
- **AND** 不遍历 B1:D1 等空候选区域

### Requirement: Public infrastructure migration

XlsxParser SHALL 使用 `parsers.utils` 模块的公共正则、MIME 推断和 URL 分类函数，并继承 `_BaseParseState`。

#### Scenario: 删除内联重复代码

- **WHEN** 迁移完成后
- **THEN** 本地 `VIDEO_URL_RE`、`HTTP_URL_RE`、`_guess_mime()`、`_is_video_url()` 和 `_read_content()` 已删除
- **AND** 改用 `parsers.utils` 中的公共实现
- **AND** `_XlsxParseState` 继承 `_BaseParseState`

#### Scenario: 链接 URL 分类与 Markdown/DOCX 解析器一致

- **WHEN** 单元格包含 `https://example.com/demo.mp4`
- **THEN** Asset 类型为 `video`
- **WHEN** 单元格包含 `https://example.com/photo.png`
- **THEN** Asset 类型为 `image`
- **WHEN** 单元格包含 `https://example.com/doc.pdf`
- **THEN** Asset 类型为 `attachment`
