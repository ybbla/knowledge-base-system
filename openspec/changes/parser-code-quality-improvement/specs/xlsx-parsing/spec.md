# XLSX Parsing (Delta)

## MODIFIED Requirements

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
- **AND** 单元格 metadata 记录公式文本（从 zip 原始 XML 轻量提取）

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

## ADDED Requirements

### Requirement: XLSX 工作簿单次加载

系统 SHALL 仅加载 XLSX 文件一次（`data_only=True`），避免双次加载导致内存翻倍。需要公式文本时从 zip 原始 XML 中按需提取。

#### Scenario: 单次加载获取缓存值

- **GIVEN** XLSX 文件的单元格同时有公式和缓存值
- **WHEN** 解析该工作簿
- **THEN** 系统 SHALL 仅执行一次 `load_workbook` 调用（`data_only=True, read_only=True`）
- **AND** 单元格 `text` 为缓存计算值
- **AND** 公式文本通过 zip 原始 XML 按需提取并写入 metadata

#### Scenario: 无缓存值时提取公式原文

- **GIVEN** XLSX 文件的公式单元格无缓存值（从未被 Excel 保存过计算结果）
- **WHEN** 解析该单元格
- **THEN** 系统从 zip 归档的 sheet XML 中提取公式文本
- **AND** `metadata.formula_value_missing` 设为 `true`
- **AND** 解析过程不因缺少缓存值而失败

### Requirement: 稀疏工作表区域检测优化

系统 SHALL 在区域检测时仅对有单元格的候选区域执行遍历，避免对笛卡尔积产生的空区域做无用检查。

#### Scenario: 稀疏数据不产生空区域遍历开销

- **GIVEN** 工作表行分组 10 组、列分组 8 组（笛卡尔积 80 个候选区域），但实际仅 3 个区域有数据
- **WHEN** 解析该工作表
- **THEN** 系统 SHALL 仅对 3 个有数据的区域执行单元格遍历
- **AND** 空候选区域在 O(1) 时间内被跳过

#### Scenario: 连续密集数据正常处理

- **GIVEN** 工作表数据为连续矩形区域 `A1:D10`
- **WHEN** 解析该工作表
- **THEN** 系统 SHALL 正确识别为单个表格区域
- **AND** 区域检测逻辑与优化前行为一致

### Requirement: 解析完成后清理原始内容

系统 SHALL 在 XLSX 解析完成后从 `doc.metadata` 中移除 `raw_content`。

#### Scenario: 解析完成后清理

- **GIVEN** XLSX 文档以 `metadata.raw_content` 形式提供原始字节
- **WHEN** 调用 `XlsxParser.parse(doc)` 成功返回
- **THEN** `result.doc.metadata` 中 SHALL 不再包含 `"raw_content"` 键
