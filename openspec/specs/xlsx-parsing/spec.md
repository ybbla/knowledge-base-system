# XLSX Parsing

## Purpose

定义 XLSX 工作簿解析能力，将工作表、表格区域、公式、超链接和资源引用转换为与现有入库管线兼容的 `ParseResult`。

> 新建自 change `phase-4-xlsx-parsing`，日期 2026-06-13。

## Requirements

### Requirement: 将 XLSX 工作簿解析为统一结构

系统 SHALL 将 `.xlsx` 工作簿解析为统一的 `ParseResult`，输出 `Document`、`ParsedElement` 和 `Asset`，并与 MarkdownParser、DocxParser 的下游契约保持兼容。

#### Scenario: 解析可见工作表

- **GIVEN** 一个 XLSX 工作簿包含两个可见工作表
- **WHEN** 调用 `XlsxParser.parse(doc)`
- **THEN** 系统为每个可见工作表生成一个 `title` 类型 ParsedElement
- **AND** `title.text` 为工作表名称
- **AND** `source_location.section_path` 包含工作表名称
- **AND** ParsedElement 的 `sequence_order` 按工作簿中的工作表顺序递增

#### Scenario: 跳过隐藏工作表

- **GIVEN** 一个 XLSX 工作簿包含隐藏工作表
- **WHEN** 调用 `XlsxParser.parse(doc)`
- **THEN** 系统 SHALL 跳过隐藏工作表的内容
- **AND** 解析过程不因隐藏工作表失败

#### Scenario: 返回 ParseResult

- **GIVEN** 一个含有工作表和表格数据的 XLSX 文档
- **WHEN** 调用 `XlsxParser.parse(doc)`
- **THEN** 系统返回 `ParseResult`
- **AND** `result.doc.source_hash` 以 `sha256:` 开头
- **AND** 所有 ParsedElement 的 `doc_id` 与输入 Document 一致

### Requirement: 将连续单元格区域解析为表格元素

系统 SHALL 将工作表中的连续非空单元格区域解析为 `table` 类型 ParsedElement，并保留行列结构用于语义层转写自然语言。

#### Scenario: 解析简单表格区域

- **GIVEN** 工作表中 `A1:B3` 是连续非空区域，第一行为表头
- **WHEN** 解析该工作表
- **THEN** 系统生成一个 `table` 类型 ParsedElement
- **AND** `structured_data.table.headers` 来自第一行
- **AND** `structured_data.table.rows` 包含后续数据行
- **AND** 每个单元格至少包含 `text` 和 `asset_ids`
- **AND** `structured_data.table.metadata.range` 记录 `A1:B3`

#### Scenario: 同一工作表存在多个独立表格区域

- **GIVEN** 工作表中 `A1:B3` 和 `D1:F4` 之间存在空列分隔
- **WHEN** 解析该工作表
- **THEN** 系统生成两个独立的 `table` 类型 ParsedElement
- **AND** 两个 table 的 `metadata.range` 分别记录各自单元格范围

#### Scenario: 孤立文本区域降级为段落

- **GIVEN** 工作表中存在单个非空单元格且周围无相邻数据
- **WHEN** 解析该工作表
- **THEN** 系统 SHALL 将该区域解析为 `paragraph` 类型 ParsedElement
- **AND** 段落 metadata 记录工作表名和单元格地址

### Requirement: 保留 XLSX 表格结构细节

系统 SHALL 在解析 XLSX 表格时保留合并单元格、公式、超链接和单元格来源信息，避免语义抽取阶段丢失关键上下文。

#### Scenario: 展开合并单元格

- **GIVEN** 工作表中 `A1:C1` 是合并单元格，左上角值为 `部门`
- **WHEN** 解析该表格区域
- **THEN** 系统 SHALL 将 `部门` 复制到合并范围内的对应单元格文本
- **AND** 被展开的单元格 metadata 记录 `merged_from="A1"`

#### Scenario: 读取公式缓存值

- **GIVEN** 单元格包含公式且工作簿保存了公式缓存值
- **WHEN** 解析该单元格
- **THEN** 系统优先将缓存值写入单元格 `text`
- **AND** 单元格 metadata 记录公式文本

#### Scenario: 公式缓存缺失

- **GIVEN** 单元格包含公式但没有可用缓存值
- **WHEN** 解析该单元格
- **THEN** 系统 SHALL 保留公式文本
- **AND** 单元格 metadata 标记 `formula_value_missing=true`
- **AND** 系统不得伪造计算结果

#### Scenario: 保留普通超链接

- **GIVEN** 单元格包含普通 HTTP 超链接
- **WHEN** 解析该单元格
- **THEN** 系统 SHALL 在单元格 metadata 中记录超链接 URL
- **AND** 若创建附件 Asset，则 Asset 的 `asset_type` 为 `attachment`，`original_uri` 为超链接 URL

### Requirement: 识别 XLSX 中的视频链接和附件资源

系统 SHALL 识别 XLSX 单元格文本或超链接中的视频 URL，并创建可追溯 Asset；普通附件链接 SHALL 至少保留来源信息。

#### Scenario: 单元格文本包含视频 URL

- **GIVEN** XLSX 单元格文本包含 `https://example.com/demo.mp4`
- **WHEN** 解析该工作表
- **THEN** 系统创建 `asset_type="video"` 的 Asset
- **AND** Asset 的 `original_uri` 为该视频 URL
- **AND** Asset 的 `status` 为 `pending`
- **AND** 对应 ParsedElement 的 `asset_ids` 引用该 Asset

#### Scenario: 单元格超链接指向附件

- **GIVEN** XLSX 单元格超链接指向 `https://example.com/manual.pdf`
- **WHEN** 解析该工作表
- **THEN** 系统 SHALL 保留该附件 URL 的来源信息
- **AND** 若创建 Asset，则 Asset 的 `asset_type` 为 `attachment`
- **AND** 阶段 4 不要求下载或递归解析该附件

### Requirement: XLSX 解析器实现统一解析器接口

系统 SHALL 实现 `DocumentParser` 抽象接口，声明 `SUPPORTED_TYPES = {"xlsx"}`，并支持从 `metadata.raw_content` 或 `file://`/`minio://` 入库链路提供的字节内容中解析工作簿。

#### Scenario: 支持类型检查

- **WHEN** 调用 `XlsxParser.supports("xlsx")`
- **THEN** 返回 `True`

#### Scenario: 不支持旧版 XLS

- **WHEN** 调用 `XlsxParser.supports("xls")`
- **THEN** 返回 `False`

#### Scenario: 无效工作簿降级为失败

- **GIVEN** 文档声明 `source_type="xlsx"` 但内容不是有效 XLSX 文件
- **WHEN** 入库管线调用解析器
- **THEN** 入库 job 状态变为 `failed`
- **AND** 错误信息包含 XLSX 解析失败原因

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
