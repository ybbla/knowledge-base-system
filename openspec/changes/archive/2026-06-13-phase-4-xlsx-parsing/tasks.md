## 1. 依赖与注册准备

- [x] 1.1 在 `requirements.txt` 增加 `openpyxl` 依赖，并确认不影响现有依赖安装。
- [x] 1.2 新建 `parsers/xlsx_parser.py`，实现 `XlsxParser(DocumentParser)` 的基础类结构和 `SUPPORTED_TYPES = {"xlsx"}`。
- [x] 1.3 在 `app/core/deps.py` 注册 `XlsxParser`，确保 `source_type="xlsx"` 可由 ParserRegistry 分派。

## 2. XLSX 文件读取与工作表遍历

- [x] 2.1 实现 XLSX 字节读取逻辑，支持 `doc.metadata["raw_content"]` 和 `file://` 来源。
- [x] 2.2 使用 `openpyxl.load_workbook` 加载工作簿，优先读取公式缓存值，并保留读取公式文本的能力。
- [x] 2.3 遍历可见工作表，为每个可见工作表生成 `title` ParsedElement，记录工作表名、顺序和标题路径。
- [x] 2.4 跳过隐藏工作表，并确保隐藏工作表不会导致解析失败。
- [x] 2.5 计算并写入 `doc.source_hash`。

## 3. 表格区域识别与结构化输出

- [x] 3.1 实现有效单元格识别规则，将非空值、公式和超链接单元格纳入区域计算。
- [x] 3.2 实现连续区域识别，按空行或空列切分同一工作表中的独立表格区域。
- [x] 3.3 将多行多列区域转换为 `table` ParsedElement，输出兼容现有格式的 `structured_data.table`。
- [x] 3.4 将单个孤立文本区域降级为 `paragraph` ParsedElement，并记录单元格地址和工作表来源。
- [x] 3.5 在 table metadata 中记录 `sheet_name`、`sheet_index`、`range` 等来源信息。

## 4. 单元格细节处理

- [x] 4.1 实现合并单元格展开，将左上角值复制到合并范围内，并记录 `merged_from` metadata。
- [x] 4.2 实现公式 metadata 记录：包含公式文本、缓存值是否缺失、最终写入的文本值。
- [x] 4.3 保留单元格超链接 URL，并写入单元格 metadata。
- [x] 4.4 识别单元格文本和超链接中的视频 URL，创建 `Asset(asset_type=video, status=pending)`。
- [x] 4.5 识别普通附件链接，创建或保留 `Asset(asset_type=attachment)` 的来源信息，且不下载附件。
- [x] 4.6 将创建的 Asset 与对应 table 或 paragraph 元素通过 `asset_ids` 关联。

## 5. 错误边界与兼容性

- [x] 5.1 对无效 XLSX 文件抛出清晰异常，使入库 job 标记为 failed 并记录错误信息。
- [x] 5.2 确保 `XlsxParser.supports("xlsx")` 返回 True，`supports("xls")` 返回 False。
- [x] 5.3 确保 Markdown/TXT/DOCX 解析行为和现有测试不受影响。
- [x] 5.4 检查大工作簿解析时的元素数量边界，避免逐单元格生成过量 ParsedElement。

## 6. 测试

- [x] 6.1 新增 `tests/test_xlsx_parser.py`，覆盖可见工作表解析、隐藏工作表跳过和 ParseResult 返回。
- [x] 6.2 测试简单表格区域解析，验证 headers、rows、cell metadata 和 range。
- [x] 6.3 测试同一工作表多个独立表格区域的拆分。
- [x] 6.4 测试合并单元格展开和 `merged_from` metadata。
- [x] 6.5 测试公式缓存值、公式文本兜底和 `formula_value_missing` 标记。
- [x] 6.6 测试视频 URL 与普通附件超链接的 Asset 创建和 `asset_ids` 关联。
- [x] 6.7 扩展 `tests/test_parser_registry.py`，验证 XlsxParser 注册和大小写不敏感分派。
- [x] 6.8 运行现有解析器、入库和 API 合约相关测试，确认回归通过。

## 7. 文档与验收

- [x] 7.1 更新必要的开发文档或示例，说明 XLSX 入库使用 `source_type="xlsx"`。
- [x] 7.2 使用一个包含多工作表、合并单元格、公式和超链接的 XLSX 样例做手工验收。
- [x] 7.3 确认 OpenSpec 规格、设计和任务与最终实现保持一致。
